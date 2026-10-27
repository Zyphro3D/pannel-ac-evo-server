# Changelog

### À venir (non publié)

**Préparation de la mise à jour 0.10 d'Assetto Corsa EVO**

- Si une mise à jour du jeu change la version réseau du serveur, le bot du panel reprend tout seul la version annoncée par le serveur à sa connexion suivante : le chat, le classement en direct et les commandes admin continuent de fonctionner sans attendre une nouvelle version du panel.
- Nouveaux tests des formats de lignes du journal du serveur (connexions, tours, secteurs, sessions, collisions) : une ligne modifiée par une mise à jour du jeu est repérée tout de suite.

**Installation**

- Les messages de fin de l'installation (adresse du panel, identifiants, étape suivante, ports à ouvrir) s'affichent en français et en anglais.

**Sécurité — corrections issues d'un audit complet du panel**

- Un pilote qui consultait les résultats effaçait les SteamID pour tout le panel (exports admin, championnats, ELO) jusqu'au redémarrage : corrigé.
- La rotation automatique relance désormais le serveur avec les mots de passe globaux (pilotes et admin) : un serveur privé ne redevient plus ouvert après une rotation.
- Les mots de passe globaux du serveur de jeu ne sont plus recopiés dans les fichiers de configuration, où tout admin pouvait les lire : seule la page Paramètres (superadmin) les gère. Les anciennes copies sont ignorées automatiquement.
- En mode HTTPS intégré (gunicorn), l'adresse transmise par un en-tête `X-Forwarded-For` n'est plus crue que si elle vient d'un proxy déclaré dans `TRUSTED_PROXIES` : l'anti-brute-force du login ne se contourne plus en changeant d'adresse factice.
- Sessions : la déconnexion et le changement de mot de passe ferment désormais toutes les sessions ouvertes du compte (autres appareils compris), et une session ne peut plus retomber sur un compte créé après la suppression d'un autre. **Après la mise à jour, chacun doit se reconnecter une fois.**
- Connexion à deux facteurs : le nombre d'essais de code est compté par le serveur (5 essais, puis 15 minutes d'attente).
- Un pilote rejeté après s'être inscrit à un événement ne figure plus sur la liste d'engagés.
- La restauration d'une sauvegarde ne reprend plus que les réglages connus du panel.
- Pilotes : les identifiants du jeu (guid) sont remplacés par des étiquettes dans les résultats ; un pilote refusé voit ses inscriptions en cours refusées et ne reçoit plus de rappel.
- Liaison Steam : le retour de Steam doit correspondre au lien demandé par la même session.
- Le direct ne peut plus être trompé par un pseudo ou un message de chat imitant une ligne du journal du serveur ; les commandes serveur n'apparaissent plus dans l'historique du chat ; les mots de passe recopiés par le serveur dans son journal sont masqués dans la page Serveur.
- Le conteneur du serveur de jeu ne reçoit plus le fichier `.env` du panel (secrets, webhooks, SMTP).
- Taille des requêtes plafonnée (64 Mo, 16 Mo pour la réception des résultats), sauf pour l'envoi de mods et de sauvegardes.
- Roulement : les noms de configuration sont revalidés et affichés comme du texte.
- Restauration : seules les vraies images sont reprises.
- Installation et mise à jour à la main : la signature de la release est exigée dès que le panel installé sait la vérifier.
- Dépendances : Pillow 13.0.0 (failles corrigées, aucune n'était atteignable par le panel) ; l'image Docker construit le CSS à partir des versions verrouillées (`npm ci`), mises à jour sans faille connue.
- Un résultat de session aux champs mal formés est refusé à la réception, au lieu d'être enregistré et de rendre l'accueil et les pages de résultats indisponibles.

### v2.4.0 — 25/10/2026

**Nouvelle interface — thème clair et thème foncé**

- Tout le panel adopte une nouvelle charte graphique : gris et rouge, polices auto-hébergées (aucun appel à un service tiers), cartes et boutons arrondis, sans décor de fond.
- **Thème clair** en plus du thème foncé : bouton soleil/lune dans la barre du haut. Par défaut le panel suit le réglage de l'appareil ; le choix est mémorisé par le navigateur.
- Les couleurs des données (secteurs violet/vert, meilleurs temps, états en ligne/arrêté, alertes) restent lisibles dans les deux thèmes ; le texte posé sur une photo de circuit reste clair dans les deux thèmes.
- **Téléphone** : plus aucune page ne déborde en largeur (testé à 390 px). Le menu « Admin », la connexion et l'inscription passent dans le menu ☰ ; les longs bandeaux passent à la ligne.
- Menus latéraux Serveur et Paramètres avec de vraies icônes ; étiquettes de type de session neutres.

**Correction — serveurs additionnels créés par une ancienne version**

- Le script d'installation reprend désormais **tout** container de serveur additionnel que compose n'a pas créé, pas seulement le premier (complète la correction de la v2.3.0).

**Licence**

- À partir de cette version, le panel est publié sous **Elastic License 2.0** (utilisation, modification et redistribution libres ; pas de revente comme service hébergé). Les versions jusqu'à v2.3.0 restent sous CC BY-NC 4.0.

### v2.3.0 — 24/10/2026

**Ajout — mise à jour du panel depuis le panel**

- **Paramètres → Panel → Mise à jour du panel** (superadmin) : version installée, dernière version publiée avec ses notes, bouton **« Mettre à jour »** et fenêtre qui suit l'avancement (téléchargement, vérification, construction, redémarrage). Un bandeau signale aussi une nouvelle version (contrôle au plus toutes les 12 h).
- **Chaque release est signée** (Ed25519, signature faite hors de la CI) : le panel vérifie le manifeste avec la clé publique qu'il embarque, puis la machine revérifie la signature **et** l'empreinte de l'archive avant d'installer. Une archive modifiée est refusée.
- **Retour arrière automatique** : si la nouvelle version ne se construit pas ou si le panel ne répond plus après 5 minutes, le code et les images précédents sont rétablis. Valable aussi quand la mise à jour est lancée à la main.
- Le panel n'obtient **aucun droit Docker de plus** : le bouton dépose seulement une demande dans le dossier `update/`, appliquée par un agent de la machine installé par le script d'installation (service systemd sous Linux, tâche planifiée à l'ouverture de session sous Windows). **Pour l'activer, relancez une fois la commande d'installation** ; ensuite, tout se fait depuis le panel.

**Correction — mise à jour avec des serveurs additionnels**

- Le fichier `docker-compose.override.yml` (généré par le panel pour les serveurs additionnels) déclarait leurs volumes Wine sans leur vrai nom : une reconstruction complète (`docker compose up`, script d'installation) échouait avec « external volume "wine_prefix_2" not found ». Le panel écrit désormais le nom réel, et le script d'installation répare une fois l'ancien fichier avant la mise à jour.
- Les containers des serveurs additionnels héritaient des étiquettes compose de l'image (service « aceserver ») : compose les prenait pour une copie du serveur principal et refusait de recréer le serveur additionnel (« container name … already in use »). Ils sont désormais créés avec leurs propres étiquettes ; le script d'installation reprend une fois les anciens (même volume Wine et mêmes fichiers, aucune perte) et relance ceux qui tournaient.

**Amélioration — reprise après un redémarrage de la machine**

- Les serveurs de jeu qui tournaient avant une coupure ou un redémarrage de la machine repartent seuls au démarrage du panel. Un serveur arrêté volontairement ou qui a planté n'est pas relancé (comportement inchangé).

### v2.2.0 — 23/10/2026

> Installation et mise à jour en **une commande**, sous Linux et désormais sous **Windows** (Docker Desktop). Toutes les étapes manuelles qui pouvaient être faites par le panel ont été retirées.

**Ajout — scripts d'installation et de mise à jour**

- **Linux** : `curl -fsSL https://raw.githubusercontent.com/Zyphro3D/pannel-ac-evo-server/master/install.sh | sudo bash`.
- **Windows** : `irm https://raw.githubusercontent.com/Zyphro3D/pannel-ac-evo-server/master/install.ps1 | iex` dans Terminal (administrateur).
- Ils font tout : Docker (proposé sous Linux, installé par winget sous Windows s'il manque), téléchargement de la dernière release **sans git**, avec vérification de son empreinte SHA-256, `.env` créé avec les clés et mots de passe générés, fichier `docker-compose.override.yml` créé, pare-feu Windows (ports du panel et du jeu, réseau privé), construction, démarrage, attente que le panel réponde, identifiants affichés à la fin.
- **Relancer la même commande met le panel à jour** : `.env`, base, configurations et fichiers du jeu sont conservés. Les installations faites avec `git clone` peuvent continuer avec `git pull`.
- Chaque release publie un fichier `SHA256SUMS`. L'archive « Windows natif » (ancien mode sans Docker) n'est plus produite : Windows passe par Docker Desktop.

**Ajout — téléchargement du serveur de jeu proposé dès la première connexion**

- Si le serveur ACE EVO n'est pas encore installé, le superadmin arrive directement sur la fenêtre **« Installer le serveur ACE EVO »** : il ne reste qu'à saisir son compte Steam. S'il la ferme, un bandeau reste affiché jusqu'à l'installation. Aucune session Steam n'est conservée.
- L'installation et les mises à jour du serveur de jeu s'affichent dans une **fenêtre de progression** au-dessus de la page (étape en clair, pourcentage du téléchargement, sortie SteamCMD repliable) au lieu d'un terminal en bas de la page Paramètres. Une mise à jour en échec se termine désormais en erreur (elle finissait sur un « ✓ »), et une première installation ne patiente plus 90 s pour rien.

**Amélioration — SteamCMD installé automatiquement**

- Plus besoin d'installer SteamCMD sur la machine (ni paquets i386) : le panel télécharge l'archive officielle de Valve dans un volume Docker au premier besoin.
- Les montages de l'hôte `/opt/steamcmd` et `${STEAM_HOME:-$HOME}/Steam` sont remplacés par les volumes `steamcmd` et `steam_session` ; la variable `STEAM_HOME` ne sert plus. Après la mise à jour, le panel réinstalle SteamCMD de lui-même à la première mise à jour du jeu.

**Correction — premier démarrage du serveur de jeu**

- Le runtime **Visual C++ 2022** est installé automatiquement dans Wine (paquet livré par Steam, sinon Microsoft) et préféré à celui de Wine, incomplet : une installation neuve plantait au premier démarrage (« unimplemented function msvcp140.dll »).
- La configuration créée au premier démarrage désignait le circuit par son identifiant (`brands_hatch`) au lieu de son nom (`Brands Hatch`) : le serveur plantait (« Trying to load a message with an empty path »).

**Correction — mise à jour du serveur de jeu**

- Un échec de téléchargement SteamCMD (« No subscription », etc.) était annoncé comme un succès : il est maintenant signalé clairement. Le compte « anonymous » n'est plus proposé par défaut : Steam lui refuse l'accès au serveur ACE EVO.

### v2.1.0 — 14/10/2026

> Cette version regroupe plusieurs chantiers menés à partir de l'analyse du serveur de jeu. Toutes les nouvelles options sont **désactivées par défaut** : une configuration existante produit exactement les mêmes arguments qu'avant. Elle ajoute aussi les outils d'administration (journal d'audit, double authentification, sauvegarde, santé, exports CSV) et la compétition (ELO, championnats). Les nouvelles tables se créent toutes seules au démarrage.

**Ajout — incidents et sanctions sur la page de détail d'un résultat**

- Le serveur de jeu écrit depuis toujours, dans chaque fichier de résultats, les **collisions** (voiture, mur ou objet, vitesse d'impact, dégâts) et les **sanctions** infligées (avertissement, secondes, drive-through, disqualification…, avec leur cause, le tour et le moment) — le panel ne les lisait pas. Deux sections apparaissent sous le classement quand la session en contient :
  - **Sanctions** : pilote, sanction (avec la pénalité de temps), cause, tour, moment, statut (en cours / levée).
  - **Incidents** : par pilote, contacts avec une autre voiture, murs, objets, chocs avec dégâts, choc maximal et **incidents par tour** ; détail des contacts entre voitures (un frottement qui produit plusieurs enregistrements n'est compté qu'une fois) et des gros chocs.
- Aucune migration : tout est relu depuis les résultats déjà importés, y compris l'historique. Vérifié sur 200 résultats réels (juin–octobre 2026).

**Ajout — onglet « Fair-play » sur la page Résultats**

- Classement des pilotes à la conduite la plus propre : **incidents par tour**, choc maximal et sanctions (dont les lourdes : drive-through, stop-and-go, disqualification), cumulés sur tous les résultats. Classé à partir de 20 tours ; en dessous le pilote reste listé, sans rang.
- Seules les sessions qui enregistrent les incidents comptent : les anciennes versions du serveur de jeu n'écrivaient ni collisions ni sanctions, leurs tours ne rendent donc pas un pilote « propre » à tort.

**Ajout — session en cours et temps restant sur « Classement en direct »**

- Un indicateur affiche le **nom de la session** (Practice, Qualifications, Warmup, Course), sa **phase** (en attente de départ, en cours, dernier tour, terminée) et un **temps restant** avec compte à rebours, qui passe en rouge au dernier tour.
- Déduit des logs du serveur de jeu : création de chaque session, « WAIT_LAST_LAP », « END_SESSION », changement de mode. Le temps restant est une **estimation** (début effectif = création + « Attente min. des joueurs », fin = début + durée) ; non affiché pour une session sans limite de temps ou sans création visible dans les dernières 24 h. Le décalage horaire des logs est détecté automatiquement. (Le bot TCP du panel ne reçoit aucun état de session du serveur : seuls les clients ayant une voiture le reçoivent.)

**Ajout — récapitulatif Discord de fin de session (option)**

- Interrupteur **« Récapitulatif de fin de session »** (Paramètres → Notifications → Discord) : à la fin de chaque session, un message sur le webhook course avec le **podium**, le **meilleur tour**, les **incidents** et les **sanctions** regroupées par pilote (les plus lourdes en premier avec leur cause). Titre personnalisable (`DISCORD_MSG_SESSION_SUMMARY`).
- Jamais pour un fichier de résultats de plus de 15 minutes (le panel réimporte les résultats manquants à chaque démarrage : pas de rafale de messages sur l'historique), jamais pour une session vide, et une erreur d'envoi ne fait jamais échouer l'import. Messages en français, comme les autres notifications Discord.

**Ajout — options de course (Serveur → configuration → Sessions → Course)**

Section repliable « Options de course », chaque réglage vérifié sur un vrai serveur de jeu avec les arguments générés par le panel :
- **Course au nombre de tours** (le panel forçait jusqu'ici une course au temps).
- **Arrêt aux stands obligatoire** : changement de pneus et/ou ravitaillement exigés, dans une fenêtre dont vous réglez la largeur (secondes), centrée au milieu de la course. Réservé aux courses au temps : en course au tour, le serveur de jeu calcule la fenêtre à partir du nombre de tours lu comme des secondes (de −146 s à +154 s pour 8 tours) ; le panel n'envoie alors pas l'arrêt obligatoire.
- **Sanctions personnalisées** : roues dehors pour une coupure, avertissements avant sanction, durée de la sanction (s'appliquent à la course uniquement, week-end ou course instantanée ; désactivé = règles d'usine du jeu).
- Valeurs bornées côté panel, champs inconnus ignorés. Prises en compte au prochain démarrage du serveur de jeu.

**Ajout — page « Accès » : liste blanche des pilotes, bannissements, lest et restricteur par joueur (option)**

- Nouvelle page **Admin → Accès**, qui écrit le fichier d'engagés lu par le serveur de jeu à son démarrage :
  - **Réserver le serveur aux pilotes approuvés** : seuls les pilotes approuvés ayant lié leur compte Steam, le bot du panel et les joueurs ayant une règle peuvent se connecter ; les autres reçoivent « User not allowed ».
  - **Bannissement par SteamID** (même sans compte sur le panel). La liste noire l'emporte sur tout, y compris sur un pilote approuvé.
  - **Handicap par joueur** : lest (0–100 kg) et restricteur (0–0,2), bornes du serveur de jeu.
- Interrupteur réservé au super-admin, désactivé par défaut (le serveur de jeu ne reçoit alors aucun fichier d'engagés, comme avant) ; un chemin d'engagés défini à la main (`SERVER_ENTRY_LIST_PATH`) reste prioritaire. Vérifié sur un vrai serveur : approuvé accepté, inconnu refusé, banni refusé, bot du panel accepté, handicap appliqué. Piège évité : le serveur de jeu ne filtre personne quand la liste blanche est vide, le fichier absent ou invalide — le panel écrit donc un joueur « sentinelle » inexistant quand aucun pilote n'est approuvé, pour ne pas ouvrir le serveur à tous par erreur.

**Ajout — modes de jeu supplémentaires**

- Le sélecteur de mode propose, en plus de Practice / Qualifications / Course / Week-end : **Course instantanée**, **Tour lancé**, **Rallye**, **A vers B** et **Test drive** (groupe « Autres modes »). Chaque mode a été lancé sur un vrai serveur de jeu.
- Course instantanée : durée, nombre de tours, arrêt obligatoire et sanctions s'appliquent comme pour une course. Tour lancé, Rallye, A vers B et Test drive : durée et heure imposées par le jeu (une note l'indique, les champs inutiles sont masqués).
- Les modes qui plantent ou ne démarrent pas (Hotstint, SRO, Superpole, Drift, Freeroam) ne sont volontairement pas proposés.

**Ajout — avertissement de capacité du circuit**

- Si le nombre maximum de joueurs dépasse le nombre de stands du circuit choisi, un avertissement s'affiche dans la configuration (les pilotes en trop ne pourraient pas être placés).

**Ajout — bannissement en direct (`\ban`)**

- Le tchat de la page Live accepte les commandes `\...`, dont `\ban <n° de voiture>` : le pilote est banni immédiatement par le serveur de jeu, **inscrit dans la page Accès** (liste noire par SteamID, donc conservé après redémarrage si le contrôle d'accès est activé) et signalé sur Discord (le bannissement manuel depuis la page Accès aussi). Sans contrôle d'accès activé, un avertissement rappelle que le bannissement ne survit pas à un redémarrage du serveur.

**Correction — noms de voitures : « Preset M4gt3 Mech 1 » au lieu de « BMW M4 GT3 »**

- La lecture du paquet `content.kspkg` ne retrouvait plus aucune voiture : les pages live et publiques affichaient des noms déduits de l'identifiant. Les noms et classes viennent maintenant de `cars.json` (officielles et mods, relu toutes les 5 minutes), l'ancienne méthode restant en secours.

**Correction — les commandes admin de la page Live (kick, pénalités, lest, restricteur, passer la session…) étaient refusées en silence**

- Le bot renvoie toutes les 20 s une requête de connexion pour éviter la coupure du serveur (seul message qui réinitialise son délai d'inactivité) ; or chaque requête de connexion **efface le statut admin** : une commande envoyée plus de ~20 s après la connexion recevait « You do not have permissions to execute this command ». Le bot se ré-élève maintenant juste avant chaque commande admin. Reproduit puis corrigé sur un vrai serveur de jeu.

**Correction — la fonction « Entry list » des événements n'avait aucun effet**

- Le fichier généré depuis les inscriptions d'un événement était écrit dans un format d'un autre jeu (`entries` / `driverName` / `carModel`) que le serveur ACE EVO ignore sans erreur. Il est maintenant au format du serveur : liste blanche = pilotes confirmés de l'événement (avec SteamID) + bot du panel, plus les règles de la page Accès. Pour qu'il soit lu, renseigner `SERVER_ENTRY_LIST_PATH` avec son chemin.

**Ajout — contacts en direct sur « Classement en direct » (option)**

- Nouvel interrupteur **« Contacts en direct »** (Paramètres → Notifications, `LIVE_COLLISIONS`, désactivé par défaut) : le panel lance alors le serveur de jeu avec `-log_debug gameplay`, ce qui lui fait écrire chaque collision dans ses logs (une douzaine de lignes par session, rien d'autre ne change). Une carte **« Derniers contacts »** affiche, du plus récent au plus ancien : qui a touché qui, un mur ou un objet, s'il y a eu des dégâts, et depuis combien de temps.
- Découvert dans le binaire du serveur : la ligne « Collision between … » existe depuis toujours mais n'est émise qu'au niveau de log « debug » du journal `gameplay`. Vérifié sur un vrai serveur avec les trois types de contact (voiture, mur, objet).
- Chaque voiture impliquée rapporte le même contact : les doublons à moins de 2 s sont fusionnés. La vitesse d'impact et la position ne sont pas journalisées en direct ; elles restent visibles après coup dans la page de détail d'un résultat.
- Prise en compte au prochain démarrage du serveur de jeu. En déploiement Docker séparé, l'image `aceserver` doit être reconstruite une fois (`docker compose build aceserver`) pour que le script de démarrage lise l'argument.

**Ajout — carte des accrochages (Résultats → Accrochages, et sur chaque page de résultat)**

- Le plan du circuit et une voiture en 3D, reliés : chaque impact enregistré par le serveur de jeu s'affiche **à l'endroit de la piste** où il a eu lieu et **à l'endroit de la voiture** qui a été touchée ; le survol d'un point l'allume des deux côtés et affiche sa fiche (type mur / voiture / objet, vitesse de l'impact, dégâts, pilote et pilote touché, session). Couleur par type, taille par vitesse ; filtres par type, vitesse minimale, dégâts, session et pilote ; vue « densité » pour repérer les virages à problème ; voiture orientable (glisser, molette, vues dessus / avant / arrière / côtés).
- Les positions du jeu sont placées sur le plan du circuit grâce à un calage par circuit (`app/calibration/track_calibration.json`, 37 circuits : de simples constantes numériques, calculées une fois en alignant le plan sur la ligne idéale du circuit ; vérifié sur 1 021 impacts réels à Spa, tous sur le tracé). Un circuit sans calage (mod, nouveau circuit) n'a pas de carte.
- La bibliothèque 3D (three.js r128, licence MIT) est fournie avec le panel : aucun service externe.

**Correction de sécurité — l'ingestion des résultats était ouverte à Internet derrière un reverse proxy**

- `/api/results/ingest` acceptait sans signature toute requête venant d'une IP privée, pour laisser passer le serveur de jeu (qui ne sait pas signer). Derrière Caddy, nginx ou Cloudflare, le panel voit l'adresse privée du proxy pour **tous** les visiteurs : n'importe qui sur Internet pouvait donc poster de faux résultats (classements, records, récapitulatif Discord). Vérifié sur une installation réelle.
- Le serveur de jeu s'authentifie maintenant par un **jeton `sig`** ajouté par le panel à l'URL de retour des résultats (valable avec ou sans proxy). Le repli sur le réseau interne n'est conservé que pour les requêtes **directes** à destination d'une adresse interne (`panel`, `127.0.0.1`, IP) et sans en-tête de proxy ; tout ce qui passe par un nom de domaine public ou un proxy est refusé. Un panel exposé directement sur une IP, sans proxy, fonctionne comme avant. Le jeton est pris en compte au prochain démarrage du serveur de jeu ; d'ici là le repli réseau interne continue de fonctionner.

**Correction — limite de débit et anti-brute-force du login partagés par tous les visiteurs derrière un proxy**

- Pour la même raison, tous les visiteurs avaient la même adresse : 10 essais de connexion par minute pour *tout le monde*, donc un seul visiteur pouvait bloquer les connexions des administrateurs. Nouvelle variable `TRUSTED_PROXIES` (adresse du proxy tel que le panel la voit) : le panel lit alors l'IP réelle du visiteur (`CF-Connecting-IP`), uniquement quand la requête vient de ce proxy. Vide par défaut = comportement historique (panel exposé directement).

**Performance — « Classement en direct » : 8 à 12 s de calcul à chaque rafraîchissement**

- Le panel relisait 24 h de logs du serveur de jeu (plusieurs Mo) via l'API Docker à chaque rafraîchissement. Les lignes déjà lues sont désormais gardées en mémoire et seules les nouvelles sont demandées, en lecture depuis la fin du journal (`tail`) : Docker relit sinon tout le fichier pour filtrer par date. Mesuré sur un serveur à 50 000 lignes : 7,7 s → 0,2 s par rafraîchissement, résultat identique à l'ancienne méthode.

**Correction — records par circuit figés au-delà de 2000 résultats**

- La page des records ne lisait que les 2000 résultats les plus anciens ; les suivants étaient ignorés. Tous les résultats sont maintenant lus, par lots.

**Ajout — journal d'audit (Admin → Journal d'audit, super-admin)**

- Enregistre qui a fait quoi, quand et depuis quelle adresse : connexions réussies et échouées, double authentification, démarrage/arrêt du serveur, changements de configuration et de réglages (les **noms** des champs modifiés, jamais leurs valeurs), comptes, bannissements et commandes en direct, événements, accès, mods, sauvegardes, exports. Aucun mot de passe ni secret n'y est écrit (un mot de passe tapé par erreur dans le champ identifiant n'est pas journalisé).
- Filtres (utilisateur, action, période, échecs seulement), pagination, export CSV, conservation configurable (`AUDIT_RETENTION_DAYS`, 365 jours par défaut).

**Ajout — authentification à deux facteurs (Mon compte)**

- Code à 6 chiffres (TOTP, compatible Google Authenticator, Aegis, 2FAS, Bitwarden…) avec QR code ; 10 codes de secours à usage unique ; un code ne peut pas être rejoué ; limitation des essais. Un super-admin peut réinitialiser le 2FA d'un compte (appareil perdu). Désactivation et nouveaux codes de secours exigent le mot de passe et un code. Comptes administrateurs uniquement.

**Ajout — sauvegarde et restauration (Admin → Sauvegarde, super-admin)**

- Un clic : zip de la base (copie cohérente), des réglages (option), des configurations serveur et des images ; téléchargement, suppression, **sauvegarde automatique quotidienne** (`BACKUP_AUTO`, `BACKUP_KEEP`).
- Restauration depuis une sauvegarde rangée ou un fichier envoyé : l'archive est vérifiée avant tout changement (noms de fichiers autorisés, tailles, intégrité et structure de la base, version compatible), l'état actuel est sauvegardé automatiquement, confirmation en tapant `RESTAURER`. Redémarrage du panel nécessaire ensuite.

**Ajout — page « Santé du serveur » (Admin)**

- Pour chaque serveur : en marche ou non, durée de fonctionnement, joueurs, CPU, mémoire, redémarrages automatiques, disponibilité sur 24 h et courbes (mesure chaque minute, conservée 7 jours) ; pour le panel : version, mémoire, base, dernier résultat reçu, dernière sauvegarde, espace disque.

**Ajout — exports CSV**

- Classement d'une session (bouton sur la page de résultat), classement fair-play, championnats, et pour les admins : tous les résultats, pilotes, journal d'audit. Fichiers UTF-8 avec séparateur point-virgule, ouvrables dans Excel ; protection contre l'injection de formules.

**Ajout — classement ELO (Résultats → ELO)**

- Niveau des pilotes d'après leurs courses, dans l'esprit de Low Fuel Motorsport : départ à 1500, comparaison de chaque pilote avec tous les autres (battre un pilote mieux classé rapporte plus), pilotes non classés pénalisés, variation réduite sur les petites grilles, 5 premières courses provisoires. Calculé depuis tout l'historique, à titre informatif.
- **Refus de participation préparé** (Admin → Accès, désactivé par défaut) : `RATING_ENFORCE` + `RATING_MIN_TO_JOIN` ajoutent à la liste noire du serveur de jeu les pilotes définitifs dont l'ELO est sous le seuil. Les pilotes provisoires ne sont jamais refusés.

**Ajout — championnats (Résultats → Championnats ; Admin → Championnats)**

- Un championnat regroupe des courses déjà jouées (les manches). Barème libre, bonus meilleur tour et pole, pires manches retirées, participation minimale pour être classé, départage par victoires puis places. Les IA sont ignorées, les places recalculées parmi les humains, un pilote qui n'a pas fait la moitié des tours est non classé dans la manche. Championnats publics ou privés, export CSV.

**Changement — le compteur fair-play peut être remis à zéro (super-admin)**

- Le suivi des incidents n'était pas actif avant la v2.1.0 : un bouton remet le compteur à zéro à la date du jour, sans rien supprimer, pour ne pas pénaliser les pilotes sur une période où ils ne pouvaient pas le savoir.

**Correction — affichage sur téléphone**

- **Page Résultats** : le menu latéral gardait sa colonne de 212 px sur téléphone et mangeait la moitié de l'écran, le contenu restait invisible. Les règles mobiles étaient écrites avant les règles de base du même menu et se faisaient écraser ; elles sont reposées après. Le menu devient une rangée d'onglets défilante.
- **Classement en direct** : la page prenait la largeur de son tableau (8 colonnes) au lieu de celle de l'écran et débordait à droite ; le tableau défile maintenant dans son cadre.
- **Bandeau cookies** : ne prend plus 7 lignes de l'écran, deux lignes suffisent.

**Divers**

- Le bandeau « nouvelles variables .env » mentionne les nouveaux interrupteurs (récapitulatif Discord, contrôle d'accès).
- Textes manquants traduits en 5 langues.
- Dépendances mises à jour : Flask 3.1.0 → 3.1.3 et python-dotenv 1.0.1 → 1.2.2 (6 vulnérabilités connues corrigées ; `pip-audit` ne signale plus rien).
- En-tête de sécurité : `object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'` ajoutés à la politique CSP.
- Le message de démarrage « RESULTS_INGEST_SECRET non défini — rejette tous les résultats » était faux ; remplacé par une information exacte.
- Le menu Admin gagne « Accès » (absent du menu bureau), « Championnats », « Santé du serveur », « Journal d'audit » et « Sauvegarde ».
- Le classement fair-play lit désormais tout l'historique (plafond de 2000 résultats retiré).
- Les textes des modèles du dossier `_partials` (formulaire de championnat, carte des accrochages) sont traduits en 5 langues ; l'extraction Babel du projet ignore ce dossier (il faut le passer explicitement).
- README mis à jour : fonctionnalités par rôle, matrice des droits, sécurité, Discord, nouvelles variables, capture de la carte des accrochages.
- 108 tests unitaires (`pytest tests/unit`, données entièrement synthétiques).

### v2.0.6 — 08/09/2026

**Ajout — message clair si l'exécutable du serveur de jeu est manquant au lancement**

- Signalé par un beta testeur : après avoir supprimé par erreur des fichiers dans `./aceserver`, le conteneur échouait avec le message Wine cryptique `ShellExecuteEx failed: File not found`, sans indication de la cause réelle. Le script de démarrage (`entrypoint.aceserver.sh`) vérifie désormais la présence de `AssettoCorsaEVOServer.exe` avant de lancer Wine, et affiche un message expliquant la cause (fichiers jamais versionnés, installés via SteamCMD) et comment réinstaller (bouton SteamCMD dans Paramètres, superadmin, ou commandes manuelles du README), en patientant/réessayant tout seul plutôt que de planter.

**Correction — la bannière "configuration modifiée, redémarrez le serveur" ne s'affichait jamais en pratique**

- Deux causes distinctes trouvées en creusant un signalement où le nom du serveur affiché sur Discord ne correspondait pas au circuit actuellement configuré dans le panel : (1) côté backend, la bannière ne se déclenchait que si le fichier de config actif avait été modifié après le démarrage, mais pas si une config **différente** avait été sélectionnée sans redémarrer — c'est ce deuxième cas qui causait la confusion. (2) côté JS, un bug indépendant masquait systématiquement la bannière dans les premières secondes suivant le chargement de la page (la logique confondait "premier statut reçu au chargement" avec "le serveur vient de redémarrer") — présent depuis l'introduction de la fonctionnalité, donc jamais réellement visible même pour son cas d'usage d'origine. Les deux corrigés : la bannière se déclenche maintenant aussi sur un changement de config non appliqué, et reste visible/se réaffiche correctement en direct au fil des rafraîchissements de statut.

### v2.0.5 — 02/09/2026

> Mise à jour du serveur de jeu ACE EVO Server 0.8.1 → **0.9.0** (build 24991735) : aucune nouvelle voiture/circuit, mais plusieurs formats de log ont changé. Corrections ci-dessous, vérifiées en conditions réelles avec un beta testeur.

**Correction — la voiture affichait encore "?" à l'arrivée d'un pilote, malgré le correctif de la v2.0.4**

- Le correctif précédent cherchait la voiture manquante dans un rescan des logs, mais la ligne qui déclenche la notification d'arrivée (`Car [...] for driver ...`) arrive systématiquement 10-20s **avant** la ligne qui contient la voiture (`connected (...) on car X`) — donc à ce moment-là, la voiture n'existe encore nulle part à trouver, dans aucune fenêtre de recherche.
- Corrigé en déplaçant le déclenchement de la notification (arrivée + changement de véhicule) sur la ligne qui porte réellement la voiture, au lieu de celle qui arrive en premier. Vérifié en conditions réelles avec un beta testeur : la bonne voiture s'affiche désormais sur Discord dès l'arrivée.

**Correction — la déconnexion d'un pilote n'était plus détectée depuis la mise à jour 0.9.0 du serveur de jeu**

- Le format est passé de `"<steamid> disconnected"` à `"Disconnected carId <carId>"` (mot en majuscule, et carId à la place du steamid) — sans ce format, un pilote restait indéfiniment "fantôme" côté panel (jamais retiré du suivi, jamais de notification Discord de départ). Corrigé en acceptant les deux formats, avec résolution du steamid depuis le carId pour le nouveau format. Vérifié avec une vraie ligne capturée en direct.

**Correction — les secteurs (S1/S2/S3) n'étaient plus capturés depuis la mise à jour 0.9.0 du serveur de jeu**

- Un préfixe `[TimelineMessage] ` est apparu devant "Split completed for car...". Corrigé en acceptant le préfixe, optionnel (compatible avec les deux formats).

**Limitation connue — le tchat en jeu n'est plus capturable par le panel depuis la mise à jour 0.9.0**

- Investigation approfondie (logs texte, flux TCP du bot, tests avec un bot de diagnostic isolé sur plusieurs types de connexion) : plus aucune trace du tchat des joueurs nulle part où le panel peut l'observer, ni en log ni via le protocole TCP existant. Piste la plus probable : le bot se connecte en mode "pilote" (nécessaire pour l'élévation admin), et les diffusions temps réel semblent désormais réservées à un mode de connexion différent ("spectateur") que le panel n'utilise pas — non confirmé, une reconstruction du mode de connexion du bot serait nécessaire pour vérifier, avec un risque sur l'élévation admin à ne pas prendre à la légère. Le reste (temps, secteurs, arrivées/départs, "Mes temps") repose sur la lecture des logs et n'est pas affecté.

**Correction — le meilleur tour du serveur pouvait encore afficher "?" pour le pilote ET la voiture**

- Cas distinct des précédents : cette fois le pilote lui-même n'était pas identifiable (`car_id_to_sid` vide), pas seulement sa voiture — typiquement quand le panel redémarre en pleine session d'un pilote déjà connecté (état en mémoire réinitialisé, aucune nouvelle ligne "connected"/"for driver" tant qu'il ne se reconnecte pas). Le repli existant ne couvrait que "voiture manquante avec pilote connu". Étendu pour reconstruire pilote et voiture ensemble via `live_state` dans tous les cas. Vérifié en conditions réelles.

**Ajout — le circuit apparaît désormais dans l'embed "meilleur tour"**

- Nouveau champ "Circuit" (ex. "Imola — GP"), à partir des infos déjà calculées pour l'enregistrement du tour en base. Corrige au passage un rafraîchissement du cache circuit/session qui pouvait échouer silencieusement (appel sans contexte applicatif Flask).

### v2.0.4 — 01/09/2026

**Correction — la voiture affichait "?" dans les notifications Discord d'arrivée et de meilleur tour**

- Signalé par un utilisateur, confirmé en conditions réelles sur un cas d'arrivée. Cause trouvée dans les vrais logs du serveur de jeu : la ligne `Car [...] for driver ...` (qui déclenche la notification d'arrivée) arrive systématiquement **avant** la ligne `connected (...) on car X` qui renseigne la voiture du pilote — pas un cas rare, l'ordre normal à chaque connexion. Le même trou touchait aussi le meilleur tour lorsqu'un pilote déjà connecté avant un (re)démarrage du panel (ou une simple coupure du flux de logs Docker) n'avait jamais sa ligne `connected` relue.
- Corrigé aux deux points d'entrée (arrivée/changement de véhicule, meilleur tour) : quand la voiture manque pour un pilote identifié, elle est désormais retrouvée via `live_state` (le même mécanisme qui reconstruit déjà le timing live en rescannant une fenêtre de logs plus large), puis mise en cache pour les événements suivants du même pilote.

**Correction — page Créer/Modifier un événement en erreur 500 systématique dès qu'une voiture avait une catégorie**

- Signalé via une issue GitHub. Cause : `{% set _ = liste.append(...) %}` (astuce Jinja habituelle pour appeler une méthode sans afficher son retour) écrasait la fonction de traduction `_()` du template avec `None` — le retour de `.append()` — pour tout le reste de la page, dès la première voiture ayant une catégorie renseignée (donc quasi toujours). Isolé à `event_form.html`, aucune autre occurrence ailleurs.
- Corrigé en renommant la variable jetable pour ne plus entrer en collision avec `_()`.

**Ajout — renommer un serveur depuis le panel**

- Bouton ✎ à côté du nom sur la page Serveurs, pour tous les serveurs y compris le principal. Répercute immédiatement le nouveau nom dans les notifications Discord d'un serveur déjà en cours d'exécution (au lieu d'attendre son prochain démarrage) ; le nom affiché dans le navigateur de serveurs du jeu, lui, reste figé dans les arguments de lancement et ne change qu'au redémarrage — précisé dans le message de confirmation.

### v2.0.3 — 27/08/2026

**Correction — un serveur additionnel (2e, 3e...) ne redémarrait plus si le dépôt n'était pas cloné dans un dossier nommé exactement `pannel-ac-evo-server`**

- Le fichier `docker-compose.override.yml` généré par le panel pour gérer les serveurs additionnels référençait une image Docker codée en dur (`pannel-ac-evo-server-aceserver`), qui ne correspond qu'au nom de projet Compose du dépôt de développement. Sur toute installation clonée dans un dossier au nom différent (ex. `~/docker/EV04` → image réelle `ev04-aceserver`), `docker-compose up` tentait de *pull* une image inexistante publiquement et échouait (`pull access denied`) — laissant le serveur additionnel bloqué sur son ancien contenu, avec un mismatch de version côté joueurs à la moindre mise à jour du jeu.
- Corrigé : le nom d'image est désormais toujours détecté dynamiquement depuis le container `ace-server` de référence (mécanisme déjà utilisé par la création directe de container, maintenant partagé par la génération du fichier compose), quel que soit le nom du dossier d'installation.

### v2.0.2 — 24/08/2026

**Ajout — page "Mes temps" refaite en grille de cartes par circuit, avec secteurs par tour**

- Reprend la mise en page de l'onglet Classement de Résultats (une carte par circuit, meilleur temps perso mis en avant — en violet plutôt qu'en rouge pour bien la distinguer d'un classement collectif). Un clic ouvre le détail : tableau trié par temps, filtrable par catégorie de véhicule, un seul temps affiché par voiture (le meilleur) plutôt que tous les tours moins bons du même véhicule.
- Nouvelles colonnes Secteur 1/2/3 dans ce tableau détaillé, calculées depuis les lignes de log `Split completed` du serveur de jeu et rattachées au tour au moment où il se termine (même formule que le timing live). Nouvelle table `lap_record.sector1_ms/2/3` (migration additive, colonnes nullable) — les tours enregistrés avant cette version n'ont pas de secteurs (affiché en tiret), rien à récupérer rétroactivement. Repris aussi dans l'archivage mensuel (`LapArchive`) pour ne pas perdre le détail après compactage au-delà du délai de rétention.

**Ajout — hooks de personnalisation locale (CSP additionnelle, HTML custom dans le `<head>`)**

- `local_settings.py` et `app/templates/_partials/local_head.html` (voir les `.example` correspondants), tous deux facultatifs et non versionnés : permettent d'ajouter des domaines à la CSP (`script-src`/`connect-src`, pour un script tiers auto-hébergé ou un outil d'analytics) et d'injecter du HTML dans le `<head>` de toutes les pages, sans forker le panel. Sans effet si absents.

**Correction — promouvoir un pilote en admin ne donnait pas les vrais droits à la reconnexion**

- La promotion créait un nouveau compte admin sans copier l'email du pilote, et la connexion ne cherchait un compte admin que par identifiant (pseudo en jeu) — jamais par email. Un pilote promu qui se reconnectait avec son email (le cas courant) retombait silencieusement sur son ancien compte pilote, sans droit admin, sans aucune erreur affichée. Les deux sont corrigés ; un message invite désormais à se reconnecter après une promotion.

**Correction — le tchat live ne récupérait pas les messages écrits en l'absence de l'utilisateur, et affichait les messages dans le mauvais sens**

- Le thread qui lit les logs du serveur de jeu (tchat, tours, connexions) n'était démarré que si un message de bienvenue était configuré : sans ce réglage, le tchat restait vide indéfiniment, et l'historique de tours ("Mes temps") n'était jamais alimenté non plus. Démarrage désormais inconditionnel. Ordre du tchat public et du flux d'activité admin inversés (nouveau message en bas, comme dans le jeu) + défilement automatique.

### v2.0.1 — 29/07/2026

**Correction — l'upload d'image véhicule/circuit et la pose de tags sur un mod nécessitaient superadmin**

- Ces trois actions (`vehicle_upload_image`, `track_upload_image`, `mod_set_tags`) avaient été mises derrière `@_superadmin_required_json` par excès de prudence lors de l'ajout de la gestion des mods (v2.0.0) — au même niveau que la gestion des comptes ou des serveurs, alors qu'elles relèvent de la gestion courante du catalogue véhicules/circuits/mods.
- Corrigé : ces trois actions ne demandent plus que le rôle Admin (comme l'upload/suppression de mods, déjà au même niveau). Réservé aux superadmins : comptes, serveurs, variables `.env`, mise à jour SteamCMD.

### v2.0.0 — 29/07/2026

**Ajout — bibliothèque de mods partagée (upload, tags manuels, PI, image de couverture, détection de collision d'identifiant)**

- Nouvelle page Mods (onglet navbar, lecture ouverte à tous les connectés — upload/suppression réservés admin) : les fichiers `.kspkg` sont scannés directement (table de fichiers de l'archive, format reverse-engineered), sans sidecar à écrire à la main.
- Upload multiple avec préchargement : plusieurs mods glissés/déposés d'un coup, image de couverture attachable par mod avant l'envoi effectif.
- Repli automatique sur le logo de marque intégré au `.kspkg` (badge) quand aucune image n'est fournie à la main (mods issus du convertisseur générique `ks_modded_car` — Honda/Nissan confirmés).
- Tags manuels (catégorie, YT/ICE/EV/Hybrid, PI) posables sur un mod depuis la page Véhicules, stockés dans `CarMeta` (nouvelle colonne `is_mod`) sans jamais toucher au catalogue officiel.
- Filtre "MODS" sur les pages Véhicules et création d'événement, tri alphanumérique cohérent avec le catalogue officiel, comptage des tags corrigé (les mods comptaient triplé dans le total "Tous").
- **Détection de collision d'identifiant** : deux mods issus du même convertisseur générique peuvent partager le même identifiant mécanique/visuel sélectionnable en jeu — confirmé en conditions réelles (un des deux mods rejoint avec "content unavailable"). Les deux mods restent affichés (les cacher rendrait la collision invisible) et un badge ⚠ apparaît sur chacun, au survol de la ligne, dans la sélection de véhicules d'un événement et sur la page Programmation.

**Correction — changer le rôle d'un pilote (admin/super admin) dupliquait le compte au lieu de le convertir**

- Signalé par un utilisateur : promouvoir un pilote ajoutait une ligne dans Comptes au lieu de faire évoluer l'existant, et redemandait un mot de passe alors que le pilote en a déjà un.
- Page Comptes unifiée (un seul menu déroulant de rôle Pilote/Admin/Super Admin par ligne, pilotes et admins dans le même tableau) et nouvelle route `POST /accounts/role` : la promotion réutilise le hash de mot de passe existant du pilote (même format Werkzeug entre `Driver` et `AdminAccount`) au lieu d'en redemander un, et reprend son Steam ID confirmé.
- Corrigé au passage : le badge SteamID validé disparaissait après une promotion (Steam ID non recopié vers le nouveau compte admin).

**Correction — faux "Fichier trop volumineux" lors de l'upload d'un mod avec image de couverture**

- La validation vérifiait `request.content_length` (toute la requête HTTP) au lieu de la taille du seul champ image — dès qu'une image de quelques Ko accompagnait un `.kspkg` volumineux, le total dépassait 5 Mo et l'upload échouait à tort.
- Corrigé : la taille est mesurée sur le flux du champ concerné uniquement.

### v1.9.6 — 22/07/2026

**Sécurité — le mot de passe admin du serveur de jeu n'apparaît plus dans l'historique de chat public ni dans les logs**

- La commande d'élévation `\admin <mot de passe>` (envoyée par le bot à chaque reconnexion, ~toutes les 60 s) transitait par `send_chat`, qui la journalisait en clair et l'ajoutait au tampon de chat exposé publiquement via `/api/live/chat-history` — lisible par tout visiteur anonyme de la page classement.
- Corrigé : les commandes serveur (préfixe « \ ») ne sont plus jamais ajoutées à l'historique public, et `\admin` est rédigé en « \admin \*\*\* » dans les logs. Les messages légitimes (bienvenue, réactions spectateurs) restent affichés.

**Correction — `/api/results/ingest` vérifie la signature HMAC avant toute lecture d'état**

- Une requête non signée déclenchait auparavant des lectures (fichier d'état, appel Docker `is_running`, comptage HTTP des joueurs) avant le rejet. La signature est désormais vérifiée en tout premier.

**Correction — l'endpoint de diagnostic `/api/live/tcp_debug` était cassé et ignorait le serveur courant**

- Import invalide (`_build_state_cached` inexistant) provoquant une erreur 500, et `server_id` non propagé. Réparé : bon import et diagnostic sur le serveur réellement sélectionné.

**Correction — réutilisation du client Docker partagé pour l'état et le redémarrage du container**

- `container_info` (sollicité en polling) et `container_restart` rouvraient une connexion Docker à chaque appel au lieu de réutiliser le client partagé.

**Correction — migration vers l'API SQLAlchemy 2.x et `datetime` timezone-aware sur les chemins restants**

- `Model.query.get()` → `db.session.get` / `db.get_or_404` ; `datetime.utcnow()` (déprécié) → `datetime.now(timezone.utc)`.

**Ajout — compte à rebours avant le prochain changement de config par inactivité**

- Sur la page Programmation et sur l'accueil (étiquette du serveur), affichage d'un compte à rebours "Prochaine config dans MM:SS" quand le roulement par inactivité est actif et qu'aucun joueur n'est connecté.
- N'apparaît que si applicable : masqué si le roulement/seuil est désactivé, ou si des joueurs sont actuellement connectés (le minuteur ne redémarre qu'une fois tout le monde reparti).
- Vérifié en isolation (délai écoulé simulé, avec/sans joueurs) : calcul correct dans les deux cas.

**Correction — le comptage de joueurs (et donc le compte à rebours ci-dessus) ne fonctionnait pas sur le serveur 1**

- Signalé par un utilisateur : le minuteur de roulement par inactivité n'apparaissait jamais sur son serveur 1 réel.
- Cause n°1 : le hostname par défaut utilisé pour interroger l'API HTTP du serveur de jeu (`ACESERVER_HOST`) était figé en dur à `aceserver` dans `Dockerfile.panel`, alors que le DNS interne Docker ne résout que `ace-server` (le `container_name` explicite du service). Ce défaut erroné faisait silencieusement échouer `get_player_count()` pour le serveur 1 (jamais pour les serveurs 2+, qui utilisent le nom de container en base de données).
- Cause n°2 : le port HTTP interne écrit dans l'état du panel au démarrage (`start_server()`) était lu depuis la variable d'environnement globale `ACESERVER_HTTP_PORT` (`8080` chez cet utilisateur) au lieu du champ `http_port` propre à chaque serveur en base (`8081`, le port réellement utilisé pour lancer le jeu). Le panel interrogeait donc le mauvais port.
- Les deux bugs sont indépendants de la fonctionnalité de compte à rebours elle-même — ils affectaient déjà silencieusement tout comptage de joueurs sur le serveur 1 avant cet ajout.
- Corrigé : hostname par défaut aligné sur le nom de container réel ; `start_server()` accepte désormais un `http_port` explicite, transmis par les 3 points d'appel (démarrage manuel, démarrage de roulement, lancement programmé) et par l'avance de roulement elle-même. Vérifié en conditions réelles sur le serveur 1 : le comptage de joueurs et le compte à rebours fonctionnent maintenant correctement.

**Ajout — bouton "Ignorer" sur le bandeau "Réglages .env ignorés"**

- Signalé par un utilisateur : le bandeau reste affiché en continu pour une divergence volontaire/déjà connue (ex. `PANEL_TITLE` différent entre `.env` et Paramètres), sans moyen de le faire taire.
- Ajout d'un bouton "Ignorer" qui mémorise la valeur `.env` exacte actuellement signalée pour chaque clé. Si `.env` ne change plus, le bandeau ne réapparaît pas pour cette clé. S'il change à nouveau (nouvelle édition), c'est une divergence différente et elle réapparaît normalement.
- Vérifié en conditions réelles : ignorer fait disparaître la divergence actuelle ; l'éditer à nouveau dans `.env` la fait réapparaître.

**Ajout — passage automatique au circuit suivant du roulement après inactivité**

- Le roulement de configs n'avançait jusqu'ici qu'à la fin d'une session réellement jouée (résultat posté par le serveur de jeu). Si personne ne se connecte, aucune session ne se termine jamais, donc le roulement restait bloqué indéfiniment sur la même config.
- Ajout d'un réglage "Passer à la configuration suivante après (minutes sans joueur)" sur la page Programmation — 0 = désactivé. Le watchdog vérifie désormais aussi le nombre de joueurs connectés, indépendamment de toute session jouée.
- Vérifié en isolation (compteur de joueurs et écoulement du temps simulés) : le déclenchement se comporte comme attendu sans affecter de serveur réel.

**Correction — sauvegarder n'importe quel onglet Paramètres réinitialisait les cases à cocher des autres onglets**

- Signalé par un utilisateur : `SESSION_COOKIE_SECURE` (onglet Panel) repassait à `false` "de temps en temps", sans action directe dessus.
- Cause : la sauvegarde d'un onglet Paramètres traitait les cases à cocher de **toutes** les sections (`_ENV_SECTIONS`), pas seulement celles de l'onglet réellement soumis. Une case décochée n'étant jamais envoyée par le navigateur, toute case absente du formulaire soumis (car appartenant à un autre onglet) était silencieusement remise à `"false"` — y compris `SESSION_COOKIE_SECURE`, `ACE_BOT_IS_ADMIN`, `MAIL_USE_TLS`, `REQUIRE_EMAIL_CONFIRMATION`. Sauvegarder l'onglet Serveur ou Notifications suffisait à casser silencieusement les réglages de l'onglet Panel.
- C'est aussi ce qui rendait le bandeau "Réglages .env ignorés" (ci-dessous) trompeur : le corriger via Paramètres puis sauvegarder n'importe quel autre onglet le recassait aussitôt.
- Corrigé : chaque case à cocher n'est désormais mise à jour que si elle appartient à l'onglet réellement soumis. Vérifié en conditions réelles (session de test authentifiée) : sauvegarder l'onglet Serveur ne touche plus `SESSION_COOKIE_SECURE`.

**Correction — le bandeau "Réglages .env ignorés" restait affiché après correction**

- Signalé par un utilisateur : `.env` et Paramètres avaient bien la même valeur pour `SESSION_COOKIE_SECURE`, mais le bandeau d'avertissement (ajouté en v1.9.5) continuait de s'afficher.
- Cause : la détection de divergence n'était calculée qu'une seule fois, au démarrage du panel (`_ENV_SETTINGS_DRIFT`). Corriger `.env` ou sauvegarder depuis Paramètres ne rafraîchissait pas cet instantané tant que le panel n'était pas redémarré.
- Corrigé : `get_env_settings_drift()` relit désormais `.env` et `settings.json` à chaque affichage, sans dépendre d'un état figé au démarrage.

### v1.9.5 — 17/07/2026

**Correction — mot de passe admin configuré via Paramètres ignoré par le bot ("reopen")**

- Signalé à nouveau après le correctif v1.9.4 : mot de passe admin bien configuré (via la page Paramètres, pas `.env`), mais le bot refuse toujours de s'élever en prétendant qu'aucun mot de passe n'est configuré.
- Cause racine trouvée en reproduisant le scénario exact : `deploy_config()` (qui écrit le fichier réellement lu par le bot pour l'élévation) relit la config source **directement depuis le disque**, sans jamais réappliquer `inject_global_server_settings()` — contrairement aux arguments de lancement envoyés au jeu, construits séparément à partir d'un dict qui, lui, avait bien reçu l'injection. Résultat : le mot de passe admin global atteignait bien le serveur de jeu, mais jamais le fichier que le bot consulte pour s'élever — peu importe le nombre de redémarrages.
- Corrigé : `deploy_config()` applique désormais `inject_global_server_settings()` sur les données avant de les écrire.
- Vérifié en reproduisant le scénario exact (config sans mot de passe propre, mot de passe configuré via Paramètres après coup, serveur redémarré) : élévation en échec avant le correctif, réussie après, sans changer quoi que ce soit d'autre.

**Correction — images véhicules/circuits absentes après un clone du repo**

- `media/` était entièrement gitignoré (destiné aux assets uploadés à l'exécution), ce qui excluait aussi les photos par défaut des véhicules/circuits officiels. Tout clone frais du repo récupérait donc un dossier `media/` vide — aucune image ne s'affichait nulle part, sauf le tracé SVG de la page Live (qui vient de `app/static/`, non concerné).
- Corrigé : `.gitignore` affiné pour ne garder l'exclusion que sur les dossiers réellement spécifiques à l'instance (`banner/`, `mail/`, `events/`) ; `media/cars/` et `media/circuits/` sont désormais versionnés.

**Ajout — avertissement quand `.env` est modifié après la première installation sans effet**

- `data/settings.json` devient la seule source de vérité dès sa création (migration one-time depuis `.env`) — toute modification de `.env` après coup est silencieusement ignorée, y compris pour des réglages sensibles (mot de passe admin, cookies sécurisés...). Aucune erreur, aucun avertissement : piège classique pour un utilisateur qui édite `.env` en pensant que ça s'applique.
- Corrigé : au démarrage, le panel compare `.env` à `settings.json` et signale toute divergence — un avertissement dans les logs (`docker compose logs panel`) et un bandeau dans l'interface (visible sur toutes les pages admin) listant les clés concernées, avec un lien direct vers Paramètres.

**Correction — mise à jour Steam : l'étape "Synchronisation véhicules et circuits" semblait bloquée**

- Signalé par un utilisateur : à la fin d'une mise à jour du serveur de jeu, l'étape de synchronisation des véhicules/circuits donnait l'impression de rester figée. Ce n'est pas un vrai blocage — le serveur de jeu met simplement plusieurs dizaines de secondes (jusqu'à 90s max) à régénérer ses fichiers après redémarrage, et cette attente ne produisait **aucun message** entre le début et la fin.
- Corrigé (`steam_updater.py`) : un message de progression ("Toujours en attente... Ns écoulées") s'affiche désormais toutes les 15 secondes pendant cette attente, pour qu'il soit clair que ça travaille toujours plutôt que d'avoir l'air figé.

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
