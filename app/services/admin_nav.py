"""Menu Admin (grand menu, version mobile) et index de la recherche « Où régler… ? ».

Une seule description sert aux trois : les groupes du menu, le panneau mobile et la
recherche, pour qu'un réglage déplacé ne soit jamais à jour à un endroit et faux à
l'autre. Choix validés le 29/10/2026 (planche « Menu Admin EvoPanel ») : 4 groupes, le
premier porte le nom du serveur choisi, une ligne d'explication sous chaque entrée.
"""
from flask import request, url_for
from flask_babel import lazy_gettext as _l

# (icône, libellé, explication, endpoint, arguments, endpoints actifs en plus, superadmin seulement)
_GROUPS = (
    ("server", _l("Serveur"), (
        ("📊", _l("Tableau de bord"), _l("état, démarrer, arrêter, journaux"),
         "admin.server", {"view": "status"}, (), False),
        ("🗂️", _l("Configurations"), _l("circuit, météo, sessions, voitures"),
         "admin.server", {"view": "configuration"}, (), False),
        ("🔄", _l("Roulement"), _l("enchaîner les configs de ce serveur"),
         "admin.server", {"view": "rotation"}, (), False),
        ("⚙️", _l("Réglages du serveur"), _l("nom, ports, mots de passe, Discord"),
         "admin.settings", {"tab": "server"}, (), True),
    )),
    ("race", _l("Courses et pilotes"), (
        ("📅", _l("Événements"), _l("soirées, inscriptions, lancement auto"),
         "events_admin.events_list", {}, ("events_admin.event_create", "events_admin.event_edit"), False),
        ("🏆", _l("Championnats"), _l("manches, points, classement"),
         "championships.championships_admin", {}, ("championships.championship_edit_page",), False),
        ("👥", _l("Pilotes"), _l("comptes à valider, profils"),
         "events_admin.drivers_list", {}, (), False),
        ("🚫", _l("Accès et sanctions"), _l("bannis, liste blanche, lest"),
         "events_admin.access_page", {}, (), False),
    )),
    ("content", _l("Contenu du jeu"), (
        ("🚗", _l("Voitures"), _l("catalogue, images"),
         "admin.vehicles", {}, ("admin.vehicle_upload_image",), False),
        ("🛣️", _l("Circuits"), _l("tracés, images"),
         "admin.tracks", {}, ("admin.track_upload_image",), False),
    )),
    ("panel", _l("Panel"), (
        ("🖥️", _l("Serveurs"), _l("ajouter un serveur, ports"),
         "admin.servers_list", {}, ("admin.server_create", "admin.server_toggle", "admin.server_delete"), True),
        ("🎨", _l("Réglages généraux"), _l("nom, logo, langue, sécurité"),
         "admin.settings", {"tab": "panel"}, (), True),
        ("🔔", _l("Notifications"), _l("Discord, e-mails, bot en jeu"),
         "admin.settings", {"tab": "notifications"}, (), True),
        ("🔑", _l("Comptes admin"), _l("organisateurs et droits"),
         "admin.settings", {"tab": "accounts"}, (), True),
        ("⬆️", _l("Mise à jour"), _l("version, mise à jour signée"),
         "admin.settings", {"tab": "panel", "_anchor": "mise-a-jour"}, (), True),
        ("💾", _l("Sauvegarde"), _l("exporter, restaurer"),
         "tools.backup_page", {}, (), True),
        ("🩺", _l("Santé et journal"), _l("état du serveur, journal d'audit"),
         "tools.health_page", {}, ("tools.audit_page",), False),
    )),
)

# Recherche : (icône, ce qu'on cherche, groupe, chemin affiché, mots-clés, endpoint, arguments, superadmin).
# Les mots-clés ne sont pas traduits : français + anglais dans la même chaîne, le reste se cherche dans les libellés traduits.
_INDEX = (
    ("⚙️", _l("Mot de passe du serveur (pilotes, admin)"), "server", _l("Réglages du serveur › Mots de passe"),
     "mot de passe password privé admin serveur jeu password private", "admin.settings", {"tab": "server", "_anchor": "srv-mots-de-passe"}, True),
    ("⚙️", _l("Ports TCP / UDP / HTTP"), "server", _l("Réglages du serveur › Réseau"),
     "port tcp udp http 9700 8081 réseau pare-feu network firewall", "admin.settings", {"tab": "server", "_anchor": "srv-reseau"}, True),
    ("⚙️", _l("Nom affiché dans la liste des serveurs"), "server", _l("Réglages du serveur › Identité"),
     "nom serveur liste navigateur joueurs max server name list browser players", "admin.settings", {"tab": "server", "_anchor": "srv-identite"}, True),
    ("⚙️", _l("Webhooks Discord de ce serveur"), "server", _l("Réglages du serveur › Discord"),
     "webhook discord serveur pilotes course drivers race", "admin.settings", {"tab": "server", "_anchor": "srv-discord"}, True),
    ("⚙️", _l("Installer ou mettre à jour le serveur de jeu"), "server", _l("Réglages du serveur › Serveur de jeu"),
     "installer steamcmd steam serveur jeu mise à jour install game server update", "admin.settings", {"tab": "server", "_anchor": "serveur-de-jeu"}, True),
    ("🗂️", _l("Circuit, météo, heure"), "server", _l("Configurations › Événement"),
     "circuit track météo heure pluie weather time rain", "admin.server", {"view": "configuration"}, False),
    ("🗂️", _l("Durées des sessions (practice, qualif, course)"), "server", _l("Configurations › Sessions"),
     "session durée qualif course warmup practice duration qualifying race", "admin.server", {"view": "configuration"}, False),
    ("🗂️", _l("Voitures autorisées"), "server", _l("Configurations › Véhicules"),
     "voiture véhicule autorisée classe car vehicle allowed class", "admin.server", {"view": "configuration"}, False),
    ("🔄", _l("Roulement et changement par inactivité"), "server", _l("Roulement"),
     "roulement rotation cycle inactivité file programmation idle queue schedule", "admin.server", {"view": "rotation"}, False),
    ("📊", _l("Démarrer, arrêter, relance automatique"), "server", _l("Tableau de bord"),
     "démarrer arrêter relance auto restart statut start stop status", "admin.server", {"view": "status"}, False),
    ("📊", _l("Journaux du serveur de jeu"), "server", _l("Tableau de bord › Logs"),
     "log logs journal erreur console error", "admin.server", {"view": "status"}, False),
    ("📅", _l("Créer une soirée course"), "race", _l("Événements › Nouvel événement"),
     "événement soirée inscription créer event race night signup create", "events_admin.events_list", {}, False),
    ("📅", _l("Lancer le serveur à l'heure de l'événement"), "race", _l("Événements › Lancement automatique"),
     "auto lancement heure planifier programmer launch schedule", "events_admin.events_list", {}, False),
    ("🏆", _l("Championnat et barème de points"), "race", _l("Championnats"),
     "championnat points barème manche saison championship points round season", "championships.championships_admin", {}, False),
    ("👥", _l("Valider les inscriptions de pilotes"), "race", _l("Pilotes"),
     "pilote inscription valider approuver compte driver approve account registration", "events_admin.drivers_list", {}, False),
    ("🚫", _l("Bannir un joueur"), "race", _l("Accès et sanctions"),
     "ban bannir banni joueur liste noire banned player blacklist", "events_admin.access_page", {}, False),
    ("🚫", _l("Liste blanche (serveur privé)"), "race", _l("Accès et sanctions"),
     "liste blanche whitelist privé private allowlist", "events_admin.access_page", {}, False),
    ("🚫", _l("Lest et restricteur par pilote"), "race", _l("Accès et sanctions"),
     "lest ballast restricteur restrictor", "events_admin.access_page", {}, False),
    ("🚗", _l("Image d'une voiture"), "content", _l("Voitures"),
     "image voiture photo véhicule car vehicle picture", "admin.vehicles", {}, False),
    ("🛣️", _l("Image d'un circuit"), "content", _l("Circuits"),
     "image circuit tracé photo track picture layout", "admin.tracks", {}, False),
    ("📦", _l("Ajouter un mod de voiture"), "content", _l("Mods (barre du haut)"),
     "mod kspkg ajouter voiture add car", "admin.mods", {}, False),
    ("🖥️", _l("Ajouter un serveur"), "panel", _l("Serveurs"),
     "ajouter serveur multi second add server multi", "admin.servers_list", {}, True),
    ("🎨", _l("Nom, logo et bannière du panel"), "panel", _l("Réglages généraux › Identité"),
     "logo bannière titre nom panel image banner title name", "admin.settings", {"tab": "panel", "_anchor": "identite"}, True),
    ("🎨", _l("Langue et fuseau horaire"), "panel", _l("Réglages généraux › Langue"),
     "langue fuseau horaire timezone language", "admin.settings", {"tab": "panel", "_anchor": "langue"}, True),
    ("🎨", _l("Adresse publique du panel"), "panel", _l("Réglages généraux › Identité"),
     "url adresse publique lien site public address link website", "admin.settings", {"tab": "panel", "_anchor": "identite"}, True),
    ("🎨", _l("Sécurité de connexion"), "panel", _l("Réglages généraux › Sécurité"),
     "sécurité connexion proxy session security login", "admin.settings", {"tab": "panel", "_anchor": "securite"}, True),
    ("🔔", _l("Webhooks Discord (principal, pilotes, course)"), "panel", _l("Notifications › Discord"),
     "webhook discord principal pilotes course récapitulatif main drivers race summary", "admin.settings", {"tab": "notifications", "_anchor": "discord-webhooks"}, True),
    ("🔔", _l("Textes des messages Discord"), "panel", _l("Notifications › Messages Discord"),
     "message texte discord personnaliser modèle text template customize", "admin.settings", {"tab": "notifications", "_anchor": "discord-messages"}, True),
    ("🔔", _l("Mention d'un rôle Discord"), "panel", _l("Notifications › Mentions"),
     "mention rôle ping discord role", "admin.settings", {"tab": "notifications", "_anchor": "discord-mentions"}, True),
    ("🔔", _l("E-mails (SMTP)"), "panel", _l("Notifications › E-mails"),
     "mail email smtp courriel", "admin.settings", {"tab": "notifications", "_anchor": "mail"}, True),
    ("🔔", _l("Messages du bot en jeu"), "panel", _l("Notifications › Bot en jeu"),
     "bot chat jeu bienvenue message tcp game welcome", "admin.settings", {"tab": "notifications", "_anchor": "bot"}, True),
    ("🔑", _l("Comptes organisateurs"), "panel", _l("Comptes admin"),
     "compte admin organisateur droits utilisateur account organiser rights user", "admin.settings", {"tab": "accounts"}, True),
    ("⬆️", _l("Mettre à jour le panel"), "panel", _l("Mise à jour"),
     "mise à jour update version upgrade", "admin.settings", {"tab": "panel", "_anchor": "mise-a-jour"}, True),
    ("💾", _l("Sauvegarder ou restaurer"), "panel", _l("Sauvegarde"),
     "sauvegarde backup restaurer export restore", "tools.backup_page", {}, True),
    ("🩺", _l("Journal d'audit (qui a fait quoi)"), "panel", _l("Santé et journal › Journal d'audit"),
     "audit journal historique qui log history who", "tools.audit_page", {}, True),
    ("🩺", _l("Ressources du serveur (CPU, mémoire, disque)"), "panel", _l("Santé et journal"),
     "santé cpu mémoire disque ressources health memory disk resources", "tools.health_page", {}, False),
    ("👤", _l("Mon mot de passe, double authentification"), "account", _l("Mon compte"),
     "2fa double authentification totp mot de passe compte two-factor password account", "admin.my_account", {}, False),
    ("👤", _l("Lier mon compte Steam"), "account", _l("Mon compte"),
     "steam lier compte link account", "admin.my_account", {}, False),
)


def _url(endpoint: str, args: dict) -> str:
    args = dict(args)
    anchor = args.pop("_anchor", None)
    return url_for(endpoint, **args) + (f"#{anchor}" if anchor else "")


def _is_active(endpoint: str, args: dict, extra: tuple) -> bool:
    if request.endpoint in extra:
        return True
    if request.endpoint != endpoint:
        return False
    # Même page, autre onglet (Paramètres, Serveur) : l'onglet doit correspondre aussi.
    for key in ("tab", "view"):
        if key in args:
            current = request.args.get(key) or {"tab": "panel", "view": "status"}[key]
            if key == "view" and current == "config_edit":
                current = "configuration"
            if current != args[key]:
                return False
    return "_anchor" not in args          # « Mise à jour » n'allume pas aussi « Réglages généraux »


def admin_menu(is_superadmin: bool, server_name: str, pending_pilots: int = 0) -> list[dict]:
    """Groupes du menu Admin pour l'utilisateur courant (entrées superadmin filtrées)."""
    scopes = {"server": server_name or str(_l("Serveur")), "race": str(_l("tous les serveurs")),
              "content": str(_l("tous les serveurs")), "panel": str(_l("tout le panel"))}
    menu = []
    for gid, title, items in _GROUPS:
        entries = [{
            "icon": icon, "label": str(label), "desc": str(desc), "url": _url(ep, args),
            "active": _is_active(ep, args, extra),
            "badge": pending_pilots if ep == "events_admin.drivers_list" and pending_pilots else 0,
        } for icon, label, desc, ep, args, extra, superadmin in items if is_superadmin or not superadmin]
        if entries:
            menu.append({"id": gid, "title": str(title), "scope": scopes[gid], "items": entries,
                         "active": any(e["active"] for e in entries)})
    return menu


def settings_index(is_superadmin: bool) -> list[dict]:
    """Entrées de la recherche « Où régler… ? » visibles par l'utilisateur courant."""
    groups = {gid: str(title) for gid, title, _items in _GROUPS}
    groups["account"] = str(_l("Mon compte"))
    return [{"icon": icon, "label": str(label), "group": groups[gid], "path": str(path),
             "keywords": kw, "url": _url(ep, args)}
            for icon, label, gid, path, kw, ep, args, superadmin in _INDEX if is_superadmin or not superadmin]
