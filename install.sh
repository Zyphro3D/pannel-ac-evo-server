#!/usr/bin/env bash
# Installation et mise à jour du panel AC EVO sous Linux (Docker).
#
#   curl -fsSL https://raw.githubusercontent.com/Zyphro3D/pannel-ac-evo-server/master/install.sh | sudo bash
#
# Relancer la même commande met le panel à jour : réglages (.env), base de données, fichiers du jeu
# et configurations sont conservés. Fait tout ce qui était manuel : Docker (proposé s'il manque),
# téléchargement de la dernière release (sans git, signature et empreinte vérifiées), .env avec clés
# et mots de passe générés, fichier override, construction et démarrage, attente que le panel réponde.
# Le serveur de jeu se télécharge ensuite depuis le panel (SteamCMD est installé automatiquement).
# Installe aussi l'agent de mise à jour (service systemd) : le bouton « Mettre à jour » du panel
# relance ce script avec --from-panel. Une mise à jour qui échoue revient à la version précédente.
#
# Options : --dir DOSSIER    dossier d'installation (défaut : /opt/pannel-ac-evo-server)
#           --version vX.Y.Z version à installer (défaut : la dernière release)
#           --source FICHIER archive locale au lieu du téléchargement (tests)
#           --yes            installe Docker sans poser la question s'il manque
#           --from-panel     mise à jour demandée depuis le panel (lancé par l'agent, pas à la main)
set -euo pipefail

# Le script remplace son propre fichier pendant une mise à jour : bash lit le script au fil de
# l'exécution, on travaille donc sur une copie.
if [ -f "$0" ] && [ -z "${ACE_PANEL_SELF:-}" ]; then
    self="$(mktemp)"
    cp "$0" "$self"
    ACE_PANEL_SELF="$self" exec bash "$self" "$@"
fi

REPO="Zyphro3D/pannel-ac-evo-server"
DIR="/opt/pannel-ac-evo-server"
VERSION=""
SOURCE=""
YES=0
FROM_PANEL=0
UNIT="ace-evo-panel-update"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m !\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m ✗\033[0m %s\n' "$*" >&2; status error "$*"; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dir)        DIR="${2:?--dir attend un dossier}"; shift 2 ;;
        --version)    VERSION="${2:?--version attend vX.Y.Z}"; shift 2 ;;
        --source)     SOURCE="${2:?--source attend une archive .zip}"; shift 2 ;;
        --yes|-y)     YES=1; shift ;;
        --from-panel) FROM_PANEL=1; YES=1; shift ;;
        -h|--help)    sed -n '2,19p' "${ACE_PANEL_SELF:-$0}" 2>/dev/null || true; exit 0 ;;
        *) printf 'Option inconnue : %s\n' "$1" >&2; exit 1 ;;
    esac
done

# Avancement lu par la page « Mise à jour du panel » (mode --from-panel). Le dossier update/ est
# accessible en écriture au panel : écriture dans un fichier temporaire créé ici puis renommé
# (un lien symbolique posé à la place de status.json serait remplacé, pas suivi).
status() {
    [ "$FROM_PANEL" -eq 1 ] || return 0
    local tmp msg
    tmp="$(mktemp "$DIR/update/.status.XXXXXX")" || return 0
    msg="$(printf '%s' "${2:-}" | tr -d '"\\' | tr '\n' ' ' | cut -c1-300)"
    printf '{"phase": "%s", "message": "%s", "version": "%s", "updated_at": %s}\n' \
        "$1" "$msg" "${VERSION#v}" "$(date +%s)" > "$tmp"
    chmod 644 "$tmp"
    mv -f "$tmp" "$DIR/update/status.json"
}

[ "$(id -u)" -eq 0 ] || die "À lancer en root : curl -fsSL https://raw.githubusercontent.com/$REPO/master/install.sh | sudo bash"

if [ "$FROM_PANEL" -eq 1 ]; then
    exec >>"$DIR/update.log" 2>&1
    echo "──── $(date '+%F %T') mise à jour demandée depuis le panel"
    # Demande déposée par le panel : seule une version au format X.Y.Z est acceptée, et elle est
    # consommée tout de suite (l'agent ne se redéclenche pas en boucle si quelque chose échoue)
    req="$(head -c 4096 "$DIR/update/request.json" 2>/dev/null || true)"
    rm -f "$DIR/update/request.json"
    v="$(printf '%s' "$req" | grep -oE '"version": *"[0-9]+\.[0-9]+\.[0-9]+"' | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || true)"
    [ -n "$v" ] || die "Demande de mise à jour illisible"
    VERSION="v$v"
    SOURCE=""
fi

# Question posée sur le terminal même quand le script arrive par « curl | bash » (stdin = le script)
ask_yes() {
    [ "$YES" -eq 1 ] && return 0
    [ -r /dev/tty ] || return 1
    local answer
    printf '%s [O/n] ' "$1" > /dev/tty
    read -r answer < /dev/tty || return 1
    case "$answer" in ""|o|O|oui|y|Y|yes) return 0 ;; *) return 1 ;; esac
}

pkg_install() {
    if command -v apt-get >/dev/null; then apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" >/dev/null
    elif command -v dnf >/dev/null; then dnf install -y -q "$@" >/dev/null
    else die "Installez d'abord : $*"; fi
}

# ── 1. Prérequis ─────────────────────────────────────────────────────────────
for tool in curl unzip; do
    command -v "$tool" >/dev/null || { say "Installation de $tool"; pkg_install "$tool"; }
done

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
    warn "Docker (avec docker compose) n'est pas installé."
    if ask_yes "Installer Docker maintenant (script officiel get.docker.com) ?"; then
        curl -fsSL https://get.docker.com | sh
    else
        die "Docker est nécessaire : https://docs.docker.com/engine/install/ puis relancez ce script."
    fi
fi
docker info >/dev/null 2>&1 || { systemctl enable --now docker >/dev/null 2>&1 || true; }
docker info >/dev/null 2>&1 || die "Le service Docker ne répond pas (systemctl status docker)."
ok "Docker $(docker version --format '{{.Server.Version}}')"

# ── 2. Récupération et vérification du panel ─────────────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; [ -n "${ACE_PANEL_SELF:-}" ] && rm -f "$ACE_PANEL_SELF"' EXIT
status download "Téléchargement de $VERSION"

# Image du panel en place : elle contient le vérificateur de signature de la version installée
PANEL_IMG="$(docker inspect --format '{{.Image}}' ace-panel 2>/dev/null || true)"
verify_signed() {
    [ -n "$PANEL_IMG" ] || return 2
    docker run --rm --entrypoint python -v "$TMP:/verify:ro" "$PANEL_IMG" \
        /panel/release/verify_release.py /verify/latest-stable.json /verify/latest-stable.json.sig \
        /verify/panel.zip "$TAG" >/dev/null 2>"$TMP/verify.err"
}

if [ -n "$SOURCE" ]; then
    [ -f "$SOURCE" ] || die "Archive introuvable : $SOURCE"
    cp "$SOURCE" "$TMP/panel.zip"
    TAG="local"
    ok "Archive locale : $SOURCE"
else
    # ACE_PANEL_RELEASE_BASE (.env) : autre dossier de releases, pour tester une mise à jour avant
    # publication (la signature reste exigée avec la clé du panel installé)
    RELEASE_BASE="$(grep -m1 '^ACE_PANEL_RELEASE_BASE=' "$DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '\r' || true)"
    if [ -n "$RELEASE_BASE" ] && [ -n "$VERSION" ]; then
        TAG="$VERSION"
        BASE="${RELEASE_BASE%/}"
    else
        API="https://api.github.com/repos/$REPO/releases/${VERSION:+tags/$VERSION}"
        [ -n "$VERSION" ] || API="${API}latest"
        RELEASE="$(curl -fsSL "$API")" || die "Release introuvable sur GitHub ($API)"
        TAG="$(printf '%s' "$RELEASE" | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
        [ -n "$TAG" ] || die "Version de la release illisible"
        BASE="https://github.com/$REPO/releases/download/$TAG"
    fi
    VERSION="$TAG"
    say "Téléchargement du panel $TAG"
    curl -fsSL -o "$TMP/panel.zip" "$BASE/pannel-ac-evo-docker-$TAG.zip" || die "Téléchargement impossible"

    status verify "Vérification de la signature"
    signed=0
    if curl -fsSL -o "$TMP/latest-stable.json" "$BASE/latest-stable.json" 2>/dev/null \
       && curl -fsSL -o "$TMP/latest-stable.json.sig" "$BASE/latest-stable.json.sig" 2>/dev/null; then
        if verify_signed; then
            signed=1
            ok "Signature et empreinte vérifiées"
        elif [ -n "$PANEL_IMG" ] && [ -s "$TMP/verify.err" ] && ! grep -q "No such file" "$TMP/verify.err"; then
            die "Release refusée : $(sed 's/^refusé : //' "$TMP/verify.err")"
        fi
    fi
    if [ "$signed" -eq 0 ]; then
        # Première installation (aucun code de confiance en place) ou release sans manifeste signé
        [ "$FROM_PANEL" -eq 0 ] || die "Release $TAG sans signature vérifiable : mise à jour refusée"
        if curl -fsSL -o "$TMP/SHA256SUMS" "$BASE/SHA256SUMS" 2>/dev/null; then
            expected="$(grep " pannel-ac-evo-docker-$TAG.zip\$" "$TMP/SHA256SUMS" | cut -d' ' -f1 || true)"
            actual="$(sha256sum "$TMP/panel.zip" | cut -d' ' -f1)"
            [ -n "$expected" ] && [ "$expected" = "$actual" ] || die "Empreinte SHA-256 incorrecte : archive refusée"
            ok "Empreinte SHA-256 vérifiée"
        else
            warn "Pas de fichier SHA256SUMS pour $TAG (release ancienne) : empreinte non vérifiée"
        fi
    fi
fi

mkdir -p "$TMP/src"
unzip -q "$TMP/panel.zip" -d "$TMP/src"
[ -f "$TMP/src/docker-compose.yml" ] || die "Archive inattendue (pas de docker-compose.yml)"

FIRST_INSTALL=1
[ -f "$DIR/.env" ] && FIRST_INSTALL=0
[ -d "$DIR/.git" ] && warn "Installation faite avec git détectée : les fichiers sont remplacés par ceux de la release (vos réglages restent)."

# ── 3. Sauvegarde pour le retour arrière (mise à jour seulement) ─────────────
# Code (hors données de l'utilisateur) et images en place : restaurés si la nouvelle version ne se
# construit pas ou si le panel ne répond plus. Rangés hors du dossier update/ partagé avec le panel.
ROLLBACK=0
if [ "$FIRST_INSTALL" -eq 0 ] && [ -n "$PANEL_IMG" ]; then
    mkdir -p "$DIR/.rollback"
    tar -C "$DIR" --exclude=./aceserver --exclude=./media --exclude=./update --exclude=./.rollback \
        --exclude=./.env --exclude=./logs --exclude=./data --exclude=./.git --exclude=./update.log \
        --exclude=./docker-compose.override.yml \
        -czf "$DIR/.rollback/code.tgz" .
    PANEL_NAME="$(docker inspect --format '{{.Config.Image}}' ace-panel)"
    SERVER_IMG="$(docker inspect --format '{{.Image}}' ace-server 2>/dev/null || true)"
    SERVER_NAME="$(docker inspect --format '{{.Config.Image}}' ace-server 2>/dev/null || true)"
    # Un tag garde les images en place : sans lui, une image qui perd son nom à la construction
    # est effacée dès qu'aucun container ne l'utilise (stockage containerd de Docker)
    # (par le nom : avant la construction il désigne l'image en service ; l'identifiant renvoyé
    # par « docker inspect » d'un container n'est pas accepté par « docker tag » avec containerd)
    docker tag "$PANEL_NAME" ace-evo-panel-rollback:panel
    [ -z "$SERVER_IMG" ] || docker tag "$SERVER_NAME" ace-evo-panel-rollback:server
    ROLLBACK=1
fi

mkdir -p "$DIR"
# Les données de l'utilisateur ne sont pas dans l'archive (.env, base, configurations, fichiers du jeu) :
# la copier par-dessus remplace le code et garde tout le reste.
cp -a "$TMP/src/." "$DIR/"
cd "$DIR"
ok "Panel $TAG copié dans $DIR"

# ── 4. Réglages (première installation seulement) ────────────────────────────
mkdir -p aceserver/configs media update
# Ce fichier doit exister avant le démarrage (sinon Docker crée un dossier à sa place)
[ -d docker-compose.override.yml ] && rmdir docker-compose.override.yml 2>/dev/null || true
[ -e docker-compose.override.yml ] || : > docker-compose.override.yml
# Override écrit par une version antérieure à 2.3.0 : volumes Wine des serveurs additionnels déclarés
# « external » sans leur vrai nom, compose refusait alors tout le projet. Le nouveau panel le régénère
# correctement, mais seulement une fois démarré : on le répare ici, une fois, à partir du volume Wine
# du serveur principal (ex. pannel-ac-evo-server_wine_prefix → …_wine_prefix_2).
if grep -q '^    external: true$' docker-compose.override.yml && ! grep -q '^    name: ' docker-compose.override.yml; then
    REF_VOL="$(docker inspect ace-server --format '{{range .Mounts}}{{if eq .Destination "/root/.wine"}}{{.Name}}{{end}}{{end}}' 2>/dev/null || true)"
    if [ -n "$REF_VOL" ]; then
        awk -v ref="$REF_VOL" '
            /^  wine_prefix_[0-9]+:$/ { n = $1; sub(/^wine_prefix_/, "", n); sub(/:$/, "", n); print; next }
            /^    external: true$/ && n != "" { print; print "    name: " ref "_" n; n = ""; next }
            { print }' docker-compose.override.yml > docker-compose.override.yml.new
        cat docker-compose.override.yml.new > docker-compose.override.yml   # même fichier (monté dans le panel)
        rm -f docker-compose.override.yml.new
        ok "Fichier override réparé (noms des volumes des serveurs additionnels)"
    fi
fi

ADMIN_PW=""
SUPERADMIN_PW=""
PANEL_PORT="$(grep -m1 '^PANEL_PORT=' .env 2>/dev/null | cut -d= -f2 || true)"   # pas de .env à la 1re installation
PANEL_PORT="${PANEL_PORT:-4300}"
IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
IP="${IP:-localhost}"

if [ "$FIRST_INSTALL" -eq 1 ]; then
    rand() { head -c 64 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-"$1"; }
    ADMIN_PW="$(rand 16)"
    SUPERADMIN_PW="$(rand 20)"
    sed -e "s|^SECRET_KEY=.*|SECRET_KEY=$(rand 64)|" \
        -e "s|^ADMIN_PASSWORD=.*|ADMIN_PASSWORD=$ADMIN_PW|" \
        -e "s|^SUPERADMIN_PASSWORD=.*|SUPERADMIN_PASSWORD=$SUPERADMIN_PW|" \
        -e "s|^RESULTS_INGEST_SECRET=.*|RESULTS_INGEST_SECRET=$(rand 32)|" \
        -e "s|^PANEL_URL=.*|PANEL_URL=http://$IP:$PANEL_PORT|" \
        -e "s|^SESSION_COOKIE_SECURE=.*|SESSION_COOKIE_SECURE=false|" \
        .env.example > .env
    chmod 600 .env
    ok "Réglages créés (.env) : clés et mots de passe générés"
else
    ok "Réglages existants conservés (.env)"
fi

# ── 5. Construction et démarrage ─────────────────────────────────────────────
# Serveurs de jeu en marche avant la mise à jour : seuls eux sont relancés ensuite (un serveur
# arrêté ne doit pas se retrouver démarré, et inscrit dans la liste publique, par une mise à jour)
RUNNING_BEFORE="$(docker compose ps --services --status running 2>/dev/null || true)"
START="panel dockerproxy"
for service in $RUNNING_BEFORE; do
    case "$service" in panel|dockerproxy|server_*) ;; *) START="$START $service" ;; esac
done

# Serveurs additionnels créés par le panel (API Docker) plutôt que par compose : compose ne les
# reconnaît pas comme les siens (étiquettes incomplètes, sans « config-hash ») et refuse de créer
# server_N sous le même nom. Ils sont retirés puis recréés par compose avec le même volume Wine et le
# même dossier de jeu (rien n'est perdu) ; ceux qui tournaient sont relancés.
while read -r svc name; do
    [ -n "$name" ] || continue
    docker inspect "$name" >/dev/null 2>&1 || continue
    hash="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.config-hash"}}' "$name" 2>/dev/null || true)"
    label="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$name" 2>/dev/null || true)"
    [ "$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)" = true ] && START="$START $svc"
    if [ -z "$hash" ] || [ "$label" != "$svc" ]; then
        docker rm -f "$name" >/dev/null
        ok "Serveur additionnel $name repris par docker compose"
    fi
done < <(awk '/^  server_[0-9]+:$/ { s = $1; sub(/:$/, "", s) }
              /^    container_name: / && s != "" { print s, $2; s = "" }' docker-compose.override.yml)

panel_up() {
    local deadline=$(( $(date +%s) + 300 ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
        curl -fsS -m 5 -o /dev/null "http://localhost:$PANEL_PORT/login" 2>/dev/null && return 0
        sleep 5
    done
    return 1
}

rollback() {
    set +e    # aller au bout du retour arrière même si une étape échoue
    warn "$1 : retour à la version précédente"
    status rollback "$1"
    tar -C "$DIR" -xzf "$DIR/.rollback/code.tgz"
    docker tag ace-evo-panel-rollback:panel "$PANEL_NAME"
    [ -z "$SERVER_IMG" ] || docker tag ace-evo-panel-rollback:server "$SERVER_NAME"
    # --force-recreate : seul le contenu de l'image a changé, compose garderait le container cassé
    # shellcheck disable=SC2086
    docker compose up -d --no-build --force-recreate $START
    panel_up
    status rolled_back "$1"
    printf '\033[1;31m ✗\033[0m %s\n' "Mise à jour annulée ($1) : version précédente rétablie" >&2
    exit 1
}

status build "Construction de $TAG"
say "Construction et démarrage (premier lancement : environ 10 minutes)"
if ! GIT_HASH="$TAG" docker compose up --build --no-start --remove-orphans; then
    [ "$ROLLBACK" -eq 1 ] && rollback "construction impossible"
    die "La construction a échoué (voir ci-dessus)"
fi
status restart "Redémarrage du panel"
# shellcheck disable=SC2086
docker compose up -d $START

say "Attente du panel"
if ! panel_up; then
    [ "$ROLLBACK" -eq 1 ] && rollback "le panel ne répond pas après la mise à jour"
    die "Le panel ne répond pas : docker compose -f $DIR/docker-compose.yml logs panel"
fi

# ── 6. Agent de mise à jour : le bouton du panel relance ce script ───────────
if command -v systemctl >/dev/null && [ -d /run/systemd/system ] && [[ "$DIR" != *[[:space:]]* ]]; then
    cat > "/etc/systemd/system/$UNIT.service" <<EOF
[Unit]
Description=Mise à jour du panel AC EVO demandée depuis le panel

[Service]
Type=oneshot
ExecStart=/bin/bash $DIR/install.sh --dir $DIR --from-panel
TimeoutStartSec=3600
EOF
    cat > "/etc/systemd/system/$UNIT.path" <<EOF
[Unit]
Description=Surveille les demandes de mise à jour du panel AC EVO

[Path]
PathExists=$DIR/update/request.json
Unit=$UNIT.service

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now "$UNIT.path" >/dev/null 2>&1
    printf '{"agent": "systemd", "installed_at": %s}\n' "$(date +%s)" > update/agent.json
    ok "Mise à jour depuis le panel activée (service $UNIT)"
else
    warn "systemd absent : la mise à jour depuis le panel n'est pas disponible (relancez ce script pour mettre à jour)"
fi

rm -rf "$DIR/.rollback"
docker rmi ace-evo-panel-rollback:panel ace-evo-panel-rollback:server >/dev/null 2>&1 || true
status "done" "Panel $TAG en ligne"
echo
ok "Panel AC EVO $TAG en ligne : http://$IP:$PANEL_PORT"
if [ "$FIRST_INSTALL" -eq 1 ]; then
    cat <<EOF

   Identifiants (à changer dans le panel, également dans $DIR/.env) :
     superadmin : $(grep -m1 '^SUPERADMIN_USERNAME=' .env | cut -d= -f2) / $SUPERADMIN_PW
     admin      : $(grep -m1 '^ADMIN_USERNAME=' .env | cut -d= -f2) / $ADMIN_PW

   Étape suivante : connectez-vous en superadmin, le panel propose de télécharger le serveur
   ACE EVO (il suffit de votre compte Steam). Ports à ouvrir vers cette machine pour les
   joueurs : 9700 TCP+UDP et 8081 TCP.
EOF
fi
