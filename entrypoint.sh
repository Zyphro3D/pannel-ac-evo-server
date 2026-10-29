#!/bin/bash
set -e

if [ ! -f /panel/.env ]; then
    echo "ERREUR : fichier /panel/.env introuvable." >&2
    echo "Copiez .env.example en .env et renseignez les valeurs avant de démarrer." >&2
    exit 1
fi

if [ -d /panel/docker-compose.override.yml ]; then
    echo "ERREUR : docker-compose.override.yml est un DOSSIER au lieu d'un fichier." >&2
    echo "Corrigez sur le host puis relancez :" >&2
    echo "  docker compose down" >&2
    echo "  sudo rm -rf docker-compose.override.yml && touch docker-compose.override.yml" >&2
    echo "  docker compose up -d --build" >&2
    exit 1
fi

# ── Panel sans root ──────────────────────────────────────────────────────────
# Le conteneur démarre en root le temps de donner à l'utilisateur « panel » ce qu'il doit pouvoir
# écrire, puis lance le panel sous cet utilisateur : une faille dans le panel ne donne plus les
# droits root du conteneur. Les installations existantes (fichiers créés en root) sont converties
# ici, au premier démarrage, sans rien à faire de plus.
PANEL_USER=panel
# Dossiers et fichiers écrits par le panel (volumes et montages de docker-compose.yml)
WRITABLE=(/panel/data /panel/media /panel/update /panel/logs /opt/steamcmd /aceserver
          /panel/.env /panel/docker-compose.override.yml)

if [ "$(id -u)" -eq 0 ] && id "$PANEL_USER" >/dev/null 2>&1 && [ "${PANEL_RUN_AS_ROOT:-}" != "1" ]; then
    uid="$(id -u "$PANEL_USER")"
    for p in "${WRITABLE[@]}"; do
        [ -e "$p" ] || continue
        # Conversion complète une seule fois (le dossier racine appartient déjà au panel ensuite) ;
        # les fichiers ajoutés plus tard en root (résultats écrits par le serveur de jeu) restent
        # lisibles, le panel n'a pas besoin de les modifier.
        if [ "$(stat -c %u:%g "$p")" != "$uid:$(id -g "$PANEL_USER")" ]; then
            echo "Droits : $p → $PANEL_USER"
            chown -R "$PANEL_USER:$PANEL_USER" "$p" 2>/dev/null || true
        fi
    done
    # Dossiers du jeu que le panel modifie à chaque démarrage ou changement de config
    for p in /aceserver/configs /aceserver/mods /aceserver/mods_disabled /aceserver/serverConfig; do
        [ -d "$p" ] && chown -R "$PANEL_USER:$PANEL_USER" "$p" 2>/dev/null || true
    done
    find /aceserver -maxdepth 1 -type f -name '.*' ! -user "$PANEL_USER" -exec chown "$PANEL_USER:$PANEL_USER" {} + 2>/dev/null || true

    # Garde-fou : un montage où chown ne s'applique pas (certains partages Windows, NFS…) ou une clé
    # TLS lisible par root seulement (/etc/letsencrypt) casserait le panel. Dans ce cas il reste en
    # root, comme avant, et le dit dans le journal.
    blocked=""
    for p in "${WRITABLE[@]}"; do
        [ -e "$p" ] || continue
        setpriv --reuid="$PANEL_USER" --regid="$PANEL_USER" --init-groups test -w "$p" || blocked="$blocked $p"
    done
    for v in SSL_CERTFILE SSL_KEYFILE; do
        f="$(grep -m1 "^$v=" /panel/.env 2>/dev/null | cut -d= -f2- | tr -d '\r"' || true)"
        [ -z "$f" ] || setpriv --reuid="$PANEL_USER" --regid="$PANEL_USER" --init-groups test -r "$f" || blocked="$blocked $f"
    done
    if [ -z "$blocked" ]; then
        export HOME=/home/$PANEL_USER
        exec setpriv --reuid="$PANEL_USER" --regid="$PANEL_USER" --init-groups --inh-caps=-all \
            python run.py
    fi
    echo "ATTENTION : le panel reste en root, accès impossible pour l'utilisateur $PANEL_USER :$blocked" >&2
fi

exec python run.py
