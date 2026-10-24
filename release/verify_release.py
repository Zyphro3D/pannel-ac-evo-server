"""Vérifie une release téléchargée avant de l'installer : signature Ed25519 du manifeste + empreinte de l'archive.

Usage : python release/verify_release.py MANIFESTE SIGNATURE ARCHIVE [VERSION_ATTENDUE]
Affiche la version vérifiée et sort avec le code 0 ; sinon un message d'erreur et le code 1.
Lancé par install.sh / install.ps1 dans l'image du panel déjà installé (le code de confiance est
celui de la version en place, pas celui qu'on s'apprête à installer).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "services"))
import panel_update  # noqa: E402  (chargé hors du paquet : pas de Flask, pas de configuration)


def main(argv: list) -> int:
    if len(argv) not in (3, 4):
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    manifest_path, sig_path, archive_path = (Path(a) for a in argv[:3])
    try:
        manifest = panel_update.verify_manifest(manifest_path.read_bytes(), sig_path.read_text())
        if len(argv) == 4 and manifest["version"] != argv[3].lstrip("v"):
            raise ValueError(f"version {manifest['version']} au lieu de {argv[3]}")
        panel_update.verify_package(manifest, archive_path)
    except Exception as e:
        print(f"refusé : {e}", file=sys.stderr)
        return 1
    print(manifest["version"])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
