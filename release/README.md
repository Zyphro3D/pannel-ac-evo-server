# Publication d'une version (mainteneur)

1. `VERSION` + entrée datée dans `CHANGELOG.md`, commit, tag `vX.Y.Z`, push : la CI construit
   `pannel-ac-evo-docker-vX.Y.Z.zip` et `SHA256SUMS` et crée la release.
2. Une fois la release publiée : `python3 release/sign_release.py` (sur la machine qui détient la
   clé de publication). Il récupère l'archive de la release, écrit le manifeste `latest-stable.json`
   (version, taille, SHA-256, notes du CHANGELOG), le signe et l'ajoute à la release avec sa `.sig`.

Sans l'étape 2, les panels installés ne voient pas la nouvelle version (le bouton « Mettre à jour »
n'accepte qu'un manifeste signé). La clé privée ne va jamais dans la CI ni dans ce dépôt ; la clé
publique correspondante est `PUBLIC_KEY_B64` dans `app/services/panel_update.py`.

`verify_release.py` est l'outil de vérification lancé par `install.sh` / `install.ps1` dans l'image
du panel déjà installé, avant toute mise à jour.
