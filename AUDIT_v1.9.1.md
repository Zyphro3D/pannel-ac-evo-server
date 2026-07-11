# Audit v1.9.1 — Liste de corrections

Audit mené par les 6 experts sur l'état du code en v1.9.1 (10/07/2026).
Les 64 items de `AUDIT.md` (v1.8.2) ont été re-vérifiés : **aucune régression**.

Cocher `[x]` quand la correction est validée et déployée. `[~]` = évalué, non appliqué (voir justification).

---

## CRITIQUES

- [x] **1** · Backend · `server_config.py:646` + `api.py:318` — `ResultsPostUrl` ne contient jamais `?server_id=N` : tous les serveurs ingèrent leurs résultats en tant que serveur 1

  `_default_config()` génère `http://{panel}:{port}/api/results/ingest` sans `server_id`, et `deploy_config()` n'injecte que `TcpPort`/`UdpPort`/`HttpPort`. Côté réception, `sid = int(request.args.get("server_id", 1) or 1)`.
  **Scénario** : le serveur 2 termine une session → POST sans `server_id` → résultat enregistré avec `server_id=1`, `try_rotation_advance()` et `update_session_state()` appelés pour le serveur 1. La rotation du mauvais serveur avance, celle du serveur 2 ne se déclenche jamais.
  **Fix appliqué (10/07/2026)** : nouvelle fonction `_results_post_url(server_id)` dans `server_config.py`, appelée par `_default_config()` (server 1) et par `deploy_config()` (server_id réel), qui injecte `?server_id={server_id}`. Testé en conditions réelles dans le conteneur : `deploy_config('Practice-spa.json', 2)` écrit bien `ResultsPostUrl: http://panel:4300/api/results/ingest?server_id=2` sur disque.

- [x] **2** · Performance · `live_state.py:174` — `build_state()` re-parse 24 h de logs container toutes les 10 s

  `iter_log_lines(since_hours=24)` récupère toute la journée de logs Docker (plusieurs Mo), les décode et les passe à ~7 regex. `_STATE_TTL = 10.0` avec le commentaire « aligns with the 15s client poll » — mais `timing.html:389` poll à **10 s**, donc le cache est expiré à quasiment chaque requête. Un seul spectateur sur `/timing` suffit à déclencher ~8640 scans complets par jour.
  Aggravant : `iter_log_lines` (`live_state.py:109`) appelait `docker.from_env()` à chaque appel au lieu de réutiliser `process_manager._get_docker_client()`.
  **Fix appliqué (10/07/2026)** :
  - `iter_log_lines()` réutilise le client Docker partagé (`process_manager._get_docker_client()`) au lieu d'en ouvrir un nouveau à chaque appel.
  - `_STATE_TTL` passé à 12 s (au-dessus des 10 s de poll réel, pour que le cache serve vraiment au lieu d'expirer avant la requête suivante).
  - `build_state()` borne la fenêtre de scan à `started_at` du serveur (timestamp de démarrage du container, déjà suivi dans l'état du process manager) plutôt qu'un plafond fixe de 24 h — sûr par construction, car aucun pilote connecté ne peut avoir une ligne "connected" antérieure au démarrage du container. Plafond de sécurité conservé à 24 h si `started_at` est inconnu ou si le serveur tourne sans interruption depuis plus longtemps.
  - **Limite connue** : un serveur qui tourne en continu depuis plus de 24 h sans redémarrage garde le plafond de 24 h (aucune régression par rapport à avant, mais pas d'amélioration sur ce cas précis). Réduire ce plafond demanderait de savoir quand le serveur a été vide pour la dernière fois (`player_count == 0`), ce qui n'est pas trivial sans un curseur incrémental — hors scope de ce fix ponctuel.
  - **Testé** : pour un serveur démarré il y a 40 min (cas réaliste après redémarrage/rotation), la fenêtre passe de 24h à 1h (÷24). `build_state()` s'exécute sans erreur, `ace-server` non perturbé pendant les tests.

---

## MOYENS

- [x] **3** · Sécurité · `api.py:392,481` — `/api/results` et `/api/results/<id>` exposent les SteamID64 de tous les pilotes à n'importe quel compte pilote connecté

  `get_result()` renvoie `"raw": json.loads(r.raw_json)` (JSON brut complet) et `get_parsed()` inclut `player_id`. Les deux routes sont en `@login_required` seul. Un pilote approuvé scripte `GET /api/results/<id>` sur toute la plage d'ID et reconstitue la table SteamID → pseudo de la communauté. C'est exactement la donnée que les items 43/44 masquent sur les endpoints live — l'effort est contourné ici.
  **Fix appliqué (10/07/2026)** : nouvelle fonction `_strip_pii_for_pilot(parsed, raw)` dans `api.py`, appelée dans `get_results()` et `get_result()` quand `not current_user.is_admin` — retire `player_id` de `parsed["standings"]` et `player_id`/`guid` de `raw["drivers"]`. Testé : un dict de test perd bien ces clés après appel.

- [x] **4** · Backend · `event_scheduler.py:85` — auto-launch d'un événement sur un serveur ≠ 1 annonce le mauvais port et le mauvais nom

  `_launch_event` appelle `build_launch_args(cfg)` sans `tcp_listener`/`udp_listener`/`server_name`, contrairement à `_do_start` (`api.py:126-127`), et n'appelle pas `deploy_config()`. Le port annoncé à Kunos devient `SERVER_TCP_PORT` (9700) au lieu du `srv.tcp_port` réel → serveur injoignable ou conflit de port.
  **Fix appliqué (10/07/2026)** : `_launch_event` récupère désormais la ligne `Server` (tcp_port/udp_port/name), appelle `deploy_config(config_name, server_id)` avant de lancer, et passe `tcp_listener`/`udp_listener`/`server_name` à `build_launch_args` — même séquence que `_do_start`.

- [x] **5** · Backend · `process_manager.py:688` — `_watchdog_loop` n'a aucun try/except autour du corps de boucle

  Contrairement à `event_scheduler._loop`. Chemin non protégé réel : `_watchdog_rotate_docker` fait `lcp.write_text(...)` (l. 473) **hors** du `try`. Une erreur disque pendant une rotation tue le thread → plus de détection de crash, plus de rotation, plus de stats, jusqu'au redémarrage du panel.
  **Fix appliqué (10/07/2026)** : le corps de la boucle `while` de `_watchdog_loop` est maintenant dans un `try/except Exception: log.exception(...)` qui continue à l'itération suivante (même style que `event_scheduler._loop`). `lcp.write_text(...)` déplacé à l'intérieur du `try` déjà présent dans `_watchdog_rotate_docker`.

- [x] **6** · Backend · `api.py:562` — `live_admin_cmd` appelle `get_driver_by_num(car_num)` sans `server_id`

  La commande part au bon serveur (`send_chat(msg, _cmd_sid)`) mais le nom du pilote pour l'embed Discord est résolu sur le leaderboard du serveur 1. Un kick sur le serveur 2 affiche « ? » ou le nom d'un pilote d'un autre serveur. Même classe de bug que l'item 15.
  **Fix appliqué (10/07/2026)** : `get_driver_by_num(car_num, _cmd_sid)`.

- [x] **7** · Backend · `discord_notifier.py:88` — les notifs joueur émises depuis les threads du bot ignorent les webhooks par-serveur

  `notify_player_join/disconnect/best_lap/vehicle_change` sont appelées depuis `_welcome_loop_*` et `_on_*_log`, threads sans app_context. `_resolve_url` teste `has_app_context()` → False → ne lit jamais `Server.discord_webhook_pilots/race` et retombe sur l'env global. Les webhooks par-serveur configurés dans l'UI sont silencieusement ignorés.
  **Fix appliqué (10/07/2026)** : `_resolve_url` ouvre désormais un contexte applicatif via `process_manager._db_context()` (déjà utilisé ailleurs dans le projet pour ce même besoin, ex. `_watchdog_notify_crash`) avant de lire la DB, au lieu d'abandonner si `has_app_context()` est faux. Testé : appel depuis un thread sans aucun contexte Flask actif → l'URL du webhook configuré en DB pour le serveur est bien résolue (au lieu de retomber sur l'env globale).

- [x] **8** · Performance · `models.py:223` — `EventRegistration.driver_id` sans index → full-scan

  `filter_by(driver_id=...)` sur la page d'accueil pour chaque pilote connecté (`public.py:112`), `pilot_dashboard` (`public.py:270`), inscription/désinscription (`public.py:315,382`). Le `UniqueConstraint("event_id", "driver_id")` crée un index composite qui ne sert pas un filtre sur `driver_id` seul.
  **Fix appliqué (10/07/2026)** : `index=True` sur la colonne (nouvelles DB) + entrée dans `_migrate_indexes()` (`CREATE INDEX IF NOT EXISTS`, DB existantes). Testé : l'index `ix_event_registration_driver_id` est bien créé au démarrage, DB neuve et DB existante.

- [x] **9** · UI · `translations/` — ~17 clés `_()` absentes ou vides des catalogues : les non-francophones voient du français

  `pybabel extract/update` n'a pas été rejoué. 13 clés absentes des 5 `.po` : `base.html:406 '(dernier)'` (= `I18N.rotLast`, aussi dans le JS de rotation) · `public.html:233 '1er'/'2e'/'3e'/'4e'` · `public.html:289 'h'/'j'/'min'` · `timing.html:109 'Administration in-game'` · `timing.html:115 'Envoyer \admin…'` · `results.html:181 'Meilleurs temps par circuit'` · `server.html:134 'Serveur ACE EVO'` · `settings.html:316 'Webhooks propres à ce serveur…'`.
  4 clés avec `msgstr ""` en en/de/es/it : `settings.html:253`, `settings.html:275`, `settings.html:757`, et `results.html:125 'Race'` (vide en `en`).
  **Fix appliqué (10/07/2026)** : `pybabel extract`/`update` rejoué (via l'API Babel plutôt qu'une regex, pour gérer correctement le wrapping multi-lignes des longs msgid) puis les 17 clés traduites dans les 5 langues, `.mo` recompilés. Testé en navigateur (Playwright) : `/timing` en anglais affiche « In-game administration », `/results?v=leaderboard` affiche « Best times by track », aucune erreur console.

- [x] **10** · Qualité · `tests/` — aucun test unitaire Python ; seul `tests/smoke.spec.js` existe

  Le smoke Playwright exige un panel démarré + credentials superadmin, donc non exécutable en CI. Zones critiques entièrement non couvertes : `results_parser.parse_result_file` (247 lignes, calcul des gaps/positions), le protocole protobuf de `ace_tcp_client.py`, `auth.py`, les migrations `_migrate_*`. Un contributeur ne peut pas refactorer ces zones sans filet.
  **Fix appliqué (10/07/2026)** : suite pytest dans `tests/unit/` (nouveau `requirements-dev.txt` + `pytest.ini`, non installés dans l'image de prod) :
  - `test_results_parser.py` — `parse_result_file()` sur une fixture synthétique (`fixtures/qualify_sample.json`) : positions, meilleur tour, secteurs, gap au leader, et confirmation que le parser ne strip PAS le PII lui-même (c'est le rôle de la route API, item 3).
  - `test_migrations.py` — DB neuve migrée sans erreur, idempotence de toutes les `_migrate_*` rejouées sur une DB déjà migrée, régression sur l'index de l'item 8, comptes admin/superadmin bien seedés.
  - `test_auth.py` — page login accessible anonyme, route admin redirige un anonyme, login correct/incorrect, accès après authentification.
  - 18 tests, tous verts (`docker run` sur l'image buildée avec le repo monté + `pip install pytest`).

---

## MINEURS

- [~] **11** · Sécurité · `app/__init__.py:428` — `'unsafe-eval'` inconditionnel dans la CSP

  Le nonce neutralise bien `'unsafe-inline'` (spec CSP3), donc l'item 23 n'est pas rouvert. Mais `'unsafe-eval'` n'est neutralisé par rien et autorise `eval()`/`new Function()`. Ni HTMX ni Chart.js n'en ont besoin : retirable sans casser le panel.
  **Vérifié (10/07/2026), non applicable** : Chart.js n'est en fait pas utilisé, mais **Alpine.js l'est** (`x-data`/`x-show`/`@click` sur `server.html`, `settings.html`, `vehicles.html`, `base.html`) — l'audit sécurité initial avait manqué cette dépendance. Alpine 3.14 évalue ses expressions via `new AsyncFunction`, qui nécessite `'unsafe-eval'`. Testé en retirant la directive : 5 `EvalError` en console rien que sur `/server`. Reverté immédiatement. Retirer `'unsafe-eval'` nécessiterait de migrer vers la build CSP dédiée d'Alpine (expressions restreintes) ou d'abandonner Alpine — hors scope d'un fix ponctuel.

- [x] **12** · Sécurité · `server_config.py:38` / `rotation_manager.py` — `deploy_config()` et `save_rotation()` n'appliquent pas `_valid_config_name()`

  Tous les autres points d'entrée le font. Un nom de rotation `../../x.json` ferait échapper `dst = runtime / config_name` hors du dossier `server-{id}/`. Admin authentifié uniquement (acteur déjà hautement privilégié) → impact négligeable, incohérence défensive à corriger.
  **Fix appliqué (10/07/2026)** : `deploy_config()` refuse (avec `log.warning`) un nom invalide en tête de fonction. `save_rotation()` filtre les noms invalides de la liste `configs` avant écriture, avec un `log.warning` listant ceux ignorés.

- [x] **13** · Sécurité · `api.py:318` — `int(request.args.get("server_id", 1) or 1)` s'exécute avant la vérification HMAC

  `?server_id=abc` → `ValueError` → 500 sans authentification. Rate-limité à 60/h, impact quasi nul. À caster défensivement.
  **Fix appliqué (10/07/2026)** : `try/except (ValueError, TypeError)` autour du cast, fallback à `1`.

- [x] **14** · Backend · `ace_tcp_client.py:359-368` — `send_chat` tient `c["lock"]` pendant `sock.sendall()`

  I/O réseau sous lock, socket bloquant (`settimeout(None)`). Si le buffer TCP est plein, `sendall` bloque en tenant le lock → `is_connected()` et la reconnexion stallent, gelant un worker sur `/api/live/tcp_status`.
  **Fix appliqué (10/07/2026)** : le socket est copié sous verrou puis le lock relâché avant `sendall()`, comme préconisé dans performance-expert.md (« acquérir, copier, relâcher »).

- [x] **15** · Backend · `ace_tcp_client.py:793` — `elevate_admin` lit `c["connected"]` sans `c["lock"]`

  Régression partielle de l'esprit de l'item 40. Impact réel faible (bool sous GIL), incohérent avec `is_connected()` corrigé juste au-dessus.
  **Fix appliqué (10/07/2026)** : lecture sous `c["lock"]`, comme `is_connected()`.

- [x] **16** · Performance · `results_parser.py:27` vs `leaderboard.py:50` — cache LRU (200) plus petit que le scan (2000)

  `build_circuits()` itère jusqu'à 2000 `SessionResult` en appelant `get_parsed` dont le LRU garde 200 entrées : au-delà de 200 résultats, chaque reconstruction (cache 60 s expiré) réévince en boucle et re-parse ~2000 JSON. Borné par le cache 60 s, mais coûteux au premier hit de `/results`.
  **Fix appliqué (10/07/2026)** : `_MAX_PARSE_CACHE` aligné sur le plus gros scan connu (2000).

- [x] **17** · Performance · `public.py:46` — `index()` (`/`) publique sans `@limiter.limit`

  La page publique qui fait le plus d'I/O (`get_running_server_info` + 50 `get_parsed` + `CarMeta`). Les autres routes publiques ont un rate limit ; la home non. Incohérent avec l'item 5 déjà corrigé.
  **Fix appliqué (10/07/2026)** : `@limiter.limit("60 per minute")`, même limite que `/results`.

- [x] **18** · Performance · `live.py:228` — SSE `/api/live/stream` : un thread lecteur + un worker Waitress bloqué par client

  `stream_with_context` monopolise un thread Waitress toute la durée de la connexion. Avec un pool borné, quelques clients saturent. Impact nul aujourd'hui : aucun template ne branche `EventSource` dessus, l'endpoint semble mort. À supprimer, ou à borner avant toute réactivation.
  **Fix appliqué (10/07/2026)** : confirmé mort (aucun `hx-ext="sse"`/`sse-connect`/`EventSource` nulle part dans le projet) — route supprimée, ainsi que la fonction jumelle `live_state.iter_log_stream()` (elle aussi sans aucun appelant). Imports devenus inutiles (`queue`, `threading`, `time`, `json`, `Response`, `stream_with_context`) retirés de `live.py`. Un import cassé a été détecté au rebuild (`live_stream` encore référencé dans `app/__init__.py` pour l'exemption CSRF) et corrigé.

- [x] **19** · Sécurité · `timing.html:291` — `car_display_name` injecté en `innerHTML` sans `_esc()`

  Contrairement à `e.name` (contrôlé par le joueur) qui est bien échappé. La donnée vient de `content.kspkg`, non contrôlable par un attaquant HTTP. Non exploitable, à échapper par principe.
  **Fix appliqué (10/07/2026)** : `_carLabel()` passe son retour par `_esc()`.

- [x] **20** · Qualité · 8 imports morts

  `admin.py:1 json` · `admin.py:7 datetime` · `events_admin.py:8 current_user` · `events_admin.py:15 htmx_toast` · `leaderboard.py:1 json` · `public.py:14 login_user` · `public.py:17 DriverStatus` · `results_parser.py:20 os`. À noter : `admin.py:621,639` ré-importent `json as _json` en inline alors que la ligne 1 l'importe déjà.
  **Fix appliqué (10/07/2026)** : les 8 imports retirés ; `_read_env_file`/`_write_env_file` utilisent maintenant le `json` de tête au lieu de `import json as _json` en inline.

- [x] **21** · Qualité · `admin.py:626,646` — `_read_env_file`/`_write_env_file` avalent l'erreur de parse de `settings.json` avec `except: pass`

  Un `settings.json` corrompu fait retomber silencieusement sur `os.environ` (lecture) ou repart d'un dict vide (écriture). L'utilisateur perd tous ses réglages sans aucune trace. Mérite un `log.warning`.
  **Fix appliqué (10/07/2026)** : `log.warning` explicite dans les deux `except`, avec le détail de l'exception.

- [x] **22** · Qualité · `config.py:54-56` / `ace_tcp_client.py:58-60,745-747,834-836` — défauts des messages bot dupliqués 4×

  Les 3 chaînes (`"Bienvenue {name} !"`, `"Rejoins le discord…"`, `"Retrouve tes resultats…"`) recopiées à 4 endroits (+ `settings.html:915`). La charte dit d'extraire à la 4ᵉ occurrence. Risque : modifier le défaut à un seul endroit.
  **Fix appliqué (10/07/2026)** : 3 constantes `DEFAULT_BOT_MSG_WELCOME/DISCORD/SITE` dans `config.py`, réutilisées par `Config` et importées dans `ace_tcp_client.py` aux 3 endroits concernés. `settings.html` (placeholder d'exemple) non touché — pas de risque de divergence fonctionnelle là, juste un texte d'aide.

- [x] **23** · UI · `tailwind.min.css` — `text-inherit` et `underline` référencées mais absentes du build purgé

  Liens `settings.html:903`, `pilot_dashboard.html:36`, `my_account.html:37` affichés sans soulignement. Rebuild Tailwind ou safelist.
  **Fix appliqué (10/07/2026)** : `npm run build` — le scanner Tailwind détectait déjà ces classes (littérales dans le HTML), le CSS compilé était simplement périmé. Vérifié : `.underline{...}` et `text-inherit` présents dans le nouveau `tailwind.min.css`.

- [x] **24** · UI · textes en dur dans des attributs

  `base.html:222 aria-label='Menu'` · `register.html:35 placeholder` · `server.html:638 title='Trier par PI'` · `my_account.html:23 placeholder` · `settings.html:764-798` (7 `placeholder=` d'exemples Discord en français).
  **Fix appliqué (10/07/2026)** : les 11 attributs passés par `_()`. Testé en navigateur : `aria-label` et `title` rendus correctement.

- [x] **25** · UI · `app.js:728,762` — les toasts de rotation réutilisent `I18N.serverStarted`/`serverStopped`

  L'utilisateur voit « Serveur démarré » alors qu'il lance le cycle de rotation. Ajouter `cycleStarted`/`cycleStopped` dans l'objet `I18N` de `base.html`.
  **Fix appliqué (10/07/2026)** : clés `cycleStarted`/`cycleStopped` ajoutées à `I18N` (base.html), `app.js` les utilise aux deux endroits concernés.

- [x] **26** · DevOps · `.env.example` — `ACESERVER_HTTP_PORT` et `ACESERVER_TCP_PORT` lus par `config.py:45,47` mais absents du fichier
  **Fix appliqué (10/07/2026)** : les deux clés ajoutées, à côté de `ACESERVER_TCP_HOST` (même catégorie : comment le panel joint le serveur de jeu).

- [x] **27** · DevOps · `docker-compose.yml:82` — port `8081:8081` codé en dur alors que `ACESERVER_HTTP_PORT` est configurable
  **Fix appliqué (10/07/2026)** : `${ACESERVER_HTTP_PORT:-8081}:${ACESERVER_HTTP_PORT:-8081}`.

- [x] **28** · DevOps · `docker-compose.yml:48` — `${HOME}/Steam:/root/Steam` fragile hors session interactive

  Sous systemd ou `sudo` sans `-E`, `$HOME` est vide → le bind devient `/Steam`, Docker crée un dossier root vide, la mise à jour SteamCMD est dégradée silencieusement.
  **Fix appliqué (10/07/2026)** : nouvelle variable `STEAM_HOME` (`.env.example`, vide par défaut) avec fallback sur `${HOME}` : `${STEAM_HOME:-${HOME}}/Steam:/root/Steam`. Validé avec `docker compose config` (résolution correcte vers `$HOME` quand `STEAM_HOME` est vide).

- [x] **29** · DevOps · `CHANGELOG.md` — le renommage `/administration/*` → `/settings/*` n'est pas signalé comme rupture d'URL

  Aucun impact DB/`.env`, mais casse les marque-pages existants. Mérite une ligne « Breaking (URLs) ».
  **Fix appliqué (10/07/2026)** : ligne « **Breaking (URLs)** » ajoutée à l'entrée v1.9.1 existante.

- [~] **30** · Qualité · fonctions longues non testées

  `results_parser.py:124 parse_result_file` (~247 l, la plus critique), `live_state.py:164 build_state` (~155 l), `public.py:47 index` (~134 l), `admin.py:393 server` (~126 l), `admin.py:656 settings` (~116 l). `parse_result_file` est le meilleur candidat au découpage (parse header / standings / gaps).
  **Évalué (10/07/2026), pas de changement de code** : c'est une suggestion de refactor, pas un bug — un découpage à l'aveugle de la fonction la plus complexe du projet sans données de production pour la validation aurait plus de risques que de bénéfices immédiats. La suite de tests ajoutée à l'item 10 sert justement de filet pour qu'un futur découpage de `parse_result_file` se fasse en sécurité ; je ne le fais pas maintenant faute d'avoir été explicitement demandé.
