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

exec python run.py
