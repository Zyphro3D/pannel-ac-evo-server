"""Signe une release publiée : manifeste latest-stable.json + .sig pour la mise à jour depuis le panel.

Usage : python release/sign_release.py [--version 2.3.0] [--zip ARCHIVE] [--key FICHIER] [--no-upload]
1. récupère l'archive Docker construite par la CI (gh release download), sauf --zip ;
2. écrit le manifeste (version, taille et SHA-256 de l'archive, notes du CHANGELOG) ;
3. le signe avec la clé Ed25519 de publication (~/.config/ace-evo-panel-release/update.key) ;
4. ajoute latest-stable.json et latest-stable.json.sig à la release GitHub (sauf --no-upload).
La clé privée ne quitte jamais cette machine : la signature se fait ici, jamais en CI.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "Zyphro3D/pannel-ac-evo-server"
sys.path.insert(0, str(ROOT / "app" / "services"))
import panel_update  # noqa: E402


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def changelog_notes(version: str) -> str:
    """Texte de l'entrée « ### vX.Y.Z » du CHANGELOG (jusqu'à l'entrée suivante)."""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^### v{re.escape(version)}\b.*?$(.*?)(?=^### |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default=(ROOT / "VERSION").read_text().strip())
    ap.add_argument("--zip", help="archive locale au lieu de celle de la release GitHub")
    ap.add_argument("--key", default=os.path.expanduser("~/.config/ace-evo-panel-release/update.key"))
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "dist" / "release"))
    a = ap.parse_args()

    v = a.version.lstrip("v")
    panel_update.parse_version(v)
    name = f"pannel-ac-evo-docker-v{v}.zip"
    out = Path(a.out) / v
    out.mkdir(parents=True, exist_ok=True)

    if a.zip:
        archive = Path(a.zip)
    else:
        archive = out / name
        archive.unlink(missing_ok=True)
        subprocess.run(["gh", "release", "download", f"v{v}", "--repo", REPO, "--pattern", name,
                        "--dir", str(out)], check=True)
    data = archive.read_bytes()

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    raw_key = Path(a.key).read_text().strip()
    key = Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(raw_key + "=" * (-len(raw_key) % 4)))
    if b64(key.public_key().public_bytes_raw()) != panel_update.PUBLIC_KEY_B64:
        sys.exit("la clé privée ne correspond pas à PUBLIC_KEY_B64 (app/services/panel_update.py)")

    manifest = {
        "app": panel_update.APP_ID,
        "version": v,
        "channel": "stable",
        "package": {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()},
        "notes": {"fr": changelog_notes(v)},
    }
    body = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    (out / "latest-stable.json").write_bytes(body)
    (out / "latest-stable.json.sig").write_text(b64(key.sign(body)) + "\n")

    # Contrôle avec le vérificateur du panel lui-même avant toute publication
    panel_update.verify_package(panel_update.verify_manifest(body, (out / "latest-stable.json.sig").read_text()), archive)
    print(f"manifeste signé : {out}/latest-stable.json ({len(data)} octets, {manifest['package']['sha256'][:12]}…)")

    if not a.no_upload:
        with tempfile.TemporaryDirectory():
            subprocess.run(["gh", "release", "upload", f"v{v}", "--repo", REPO, "--clobber",
                            str(out / "latest-stable.json"), str(out / "latest-stable.json.sig")], check=True)
        print(f"ajouté à la release v{v}")


if __name__ == "__main__":
    main()
