"""CSP : aucun gestionnaire en ligne (onclick=…). Ils passent par data-on (static/js/app.js), et l'en-tête
pose script-src-attr 'none'. Un attribut on* oublié ne marcherait plus dans le navigateur : on le refuse ici."""
import re
from pathlib import Path

RACINE = Path(__file__).resolve().parents[2] / "app"
ATTR_ON = re.compile(r"""\son(?:click|change|input|submit|keydown|keyup|keypress|load|error|focus|blur|mouse\w+|touch\w+)\s*=\s*["'\\]""", re.I)


def test_aucun_gestionnaire_en_ligne_dans_les_gabarits_et_le_js():
    fautes = []
    for f in list((RACINE / "templates").rglob("*.html")) + list((RACINE / "static" / "js").glob("*.js")):
        if f.name.endswith(".min.js"):
            continue
        for n, ligne in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if ATTR_ON.search(ligne) and not ligne.lstrip().startswith("//"):
                fautes.append(f"{f.relative_to(RACINE)}:{n}")
    assert not fautes, "gestionnaires en ligne (utiliser data-on) : " + ", ".join(fautes)


def test_entete_csp_interdit_les_gestionnaires_en_ligne(admin_client):
    csp = admin_client.get("/").headers["Content-Security-Policy"]
    assert "script-src-attr 'none'" in csp
