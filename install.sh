#!/usr/bin/env bash
# Installation et mise à jour du panel AC EVO sous Linux (Docker).
#
#   curl -fsSL https://raw.githubusercontent.com/Zyphro3D/pannel-ac-evo-server/master/install.sh | sudo bash
#
# Relancer la même commande met le panel à jour : réglages (.env), base de données, fichiers du jeu
# et configurations sont conservés. Fait tout ce qui était manuel : Docker (proposé s'il manque),
# téléchargement de la dernière release (sans git, empreinte SHA-256 vérifiée), .env avec clés et
# mots de passe générés, fichier override, construction et démarrage, attente que le panel réponde.
# Le serveur de jeu se télécharge ensuite depuis le panel (SteamCMD est installé automatiquement).
#
# Options : --dir DOSSIER    dossier d'installation (défaut : /opt/pannel-ac-evo-server)
#           --version vX.Y.Z version à installer (défaut : la dernière release)
#           --source FICHIER archive locale au lieu du téléchargement (tests)
#           --yes            installe Docker sans poser la question s'il manque
set -euo pipefail

REPO="Zyphro3D/pannel-ac-evo-server"
DIR="/opt/pannel-ac-evo-server"
VERSION=""
SOURCE=""
YES=0

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m !\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m ✗\033[0m %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --dir)     DIR="${2:?--dir attend un dossier}"; shift 2 ;;
        --version) VERSION="${2:?--version attend vX.Y.Z}"; shift 2 ;;
        --source)  SOURCE="${2:?--source attend une archive .zip}"; shift 2 ;;
        --yes|-y)  YES=1; shift ;;
        -h|--help) sed -n '2,17p' "$0" 2>/dev/null || true; exit 0 ;;
        *) die "Option inconnue : $1" ;;
    esac
done

[ "$(id -u)" -eq 0 ] || die "À lancer en root : curl -fsSL https://raw.githubusercontent.com/$REPO/master/install.sh | sudo bash"

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

# ── 2. Récupération du panel ─────────────────────────────────────────────────
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ -n "$SOURCE" ]; then
    [ -f "$SOURCE" ] || die "Archive introuvable : $SOURCE"
    cp "$SOURCE" "$TMP/panel.zip"
    TAG="local"
    ok "Archive locale : $SOURCE"
else
    API="https://api.github.com/repos/$REPO/releases/${VERSION:+tags/$VERSION}"
    [ -n "$VERSION" ] || API="${API}latest"
    RELEASE="$(curl -fsSL "$API")" || die "Release introuvable sur GitHub ($API)"
    TAG="$(printf '%s' "$RELEASE" | grep -m1 '"tag_name"' | sed -E 's/.*"tag_name": *"([^"]+)".*/\1/')"
    [ -n "$TAG" ] || die "Version de la release illisible"
    BASE="https://github.com/$REPO/releases/download/$TAG"
    say "Téléchargement du panel $TAG"
    curl -fsSL -o "$TMP/panel.zip" "$BASE/pannel-ac-evo-docker-$TAG.zip" || die "Téléchargement impossible"
    if curl -fsSL -o "$TMP/SHA256SUMS" "$BASE/SHA256SUMS" 2>/dev/null; then
        expected="$(grep " pannel-ac-evo-docker-$TAG.zip\$" "$TMP/SHA256SUMS" | cut -d' ' -f1 || true)"
        actual="$(sha256sum "$TMP/panel.zip" | cut -d' ' -f1)"
        [ -n "$expected" ] && [ "$expected" = "$actual" ] || die "Empreinte SHA-256 incorrecte : archive refusée"
        ok "Empreinte SHA-256 vérifiée"
    else
        warn "Pas de fichier SHA256SUMS pour $TAG (release ancienne) : empreinte non vérifiée"
    fi
fi

mkdir -p "$TMP/src"
unzip -q "$TMP/panel.zip" -d "$TMP/src"
[ -f "$TMP/src/docker-compose.yml" ] || die "Archive inattendue (pas de docker-compose.yml)"

FIRST_INSTALL=1
[ -f "$DIR/.env" ] && FIRST_INSTALL=0
[ -d "$DIR/.git" ] && warn "Installation faite avec git détectée : les fichiers sont remplacés par ceux de la release (vos réglages restent)."

mkdir -p "$DIR"
# Les données de l'utilisateur ne sont pas dans l'archive (.env, base, configurations, fichiers du jeu) :
# la copier par-dessus remplace le code et garde tout le reste.
cp -a "$TMP/src/." "$DIR/"
cd "$DIR"
ok "Panel $TAG copié dans $DIR"

# ── 3. Réglages (première installation seulement) ────────────────────────────
mkdir -p aceserver/configs media
# Ce fichier doit exister avant le démarrage (sinon Docker crée un dossier à sa place)
[ -d docker-compose.override.yml ] && rmdir docker-compose.override.yml 2>/dev/null || true
[ -e docker-compose.override.yml ] || : > docker-compose.override.yml

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

# ── 4. Construction et démarrage ─────────────────────────────────────────────
# Serveurs de jeu en marche avant la mise à jour : seuls eux sont relancés ensuite (un serveur
# arrêté ne doit pas se retrouver démarré, et inscrit dans la liste publique, par une mise à jour)
RUNNING_BEFORE="$(docker compose ps --services --status running 2>/dev/null || true)"

say "Construction et démarrage (premier lancement : environ 10 minutes)"
GIT_HASH="$TAG" docker compose up --build --no-start --remove-orphans
START="panel dockerproxy"
for service in $RUNNING_BEFORE; do
    case "$service" in panel|dockerproxy) ;; *) START="$START $service" ;; esac
done
# shellcheck disable=SC2086
docker compose up -d $START

say "Attente du panel"
for _ in $(seq 1 60); do
    curl -fsS -o /dev/null "http://localhost:$PANEL_PORT/login" 2>/dev/null && break
    sleep 5
done
curl -fsS -o /dev/null "http://localhost:$PANEL_PORT/login" 2>/dev/null \
    || die "Le panel ne répond pas : docker compose -f $DIR/docker-compose.yml logs panel"

echo
ok "Panel AC EVO $TAG en ligne : http://$IP:$PANEL_PORT"
if [ "$FIRST_INSTALL" -eq 1 ]; then
    cat <<EOF

   Identifiants (à changer dans le panel, également dans $DIR/.env) :
     superadmin : $(grep -m1 '^SUPERADMIN_USERNAME=' .env | cut -d= -f2) / $SUPERADMIN_PW
     admin      : $(grep -m1 '^ADMIN_USERNAME=' .env | cut -d= -f2) / $ADMIN_PW

   Étape suivante : connectez-vous en superadmin, puis Paramètres → mise à jour du serveur
   (SteamCMD) pour télécharger le serveur ACE EVO. Ports à ouvrir vers cette machine pour
   les joueurs : 9700 TCP+UDP et 8081 TCP.
EOF
fi
