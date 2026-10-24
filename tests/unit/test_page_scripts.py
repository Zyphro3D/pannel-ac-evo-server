import re
import shutil
import subprocess

import pytest

from app.services import panel_update

# Une apostrophe dans un texte traduit inséré entre '…' cassait tout le script de la page
# (« Unexpected identifier », vu par le test de fumée de la CI) : on vérifie la syntaxe ici.
pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node absent")


@pytest.mark.parametrize("tab", ["panel", "server", "notifications", "accounts"])
def test_scripts_des_parametres_syntaxe_js_valide(admin_client, monkeypatch, tmp_path, tab):
    monkeypatch.setattr(panel_update, "check_in_background", lambda current: None)
    html = admin_client.get(f"/settings?tab={tab}").get_data(as_text=True)
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    assert scripts
    js = tmp_path / "page.js"
    js.write_text("\n;\n".join(scripts), encoding="utf-8")
    r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
