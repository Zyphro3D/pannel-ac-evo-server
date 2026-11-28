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


def test_entete_csp_sans_eval_ni_script_en_ligne(admin_client):
    csp = admin_client.get("/").headers["Content-Security-Policy"]
    script_src = next(d for d in csp.split(";") if d.strip().startswith("script-src "))
    assert "'unsafe-eval'" not in script_src and "'unsafe-inline'" not in script_src, script_src
    assert "'nonce-" in script_src


ATTR_ALPINE = re.compile(r"""\s(x-[\w:.-]+|@[\w:.-]+)=(?:"([^"]*)"|'([^']*)')""", re.S)
INTERDIT_CSP = re.compile(r"=>|`|\$\{|\b(document|window|console|Math|JSON|setTimeout|fetch|localStorage|location)\b|\$dispatch|\b\w+\.\w+\s*=[^=]")


def test_expressions_alpine_compatibles_avec_la_version_csp():
    """La version CSP d'Alpine n'évalue que des expressions simples : la logique va dans Alpine.data (app.js)."""
    fautes = []
    for f in list((RACINE / "templates").rglob("*.html")) + [RACINE / "static" / "js" / "app.js"]:
        texte = f.read_text(encoding="utf-8")
        for m in ATTR_ALPINE.finditer(texte):
            valeur = m.group(2) if m.group(2) is not None else m.group(3)
            if INTERDIT_CSP.search(valeur) or m.group(1) == "x-html":
                fautes.append(f"{f.relative_to(RACINE)}:{texte[:m.start()].count(chr(10)) + 1} {m.group(1)}")
    assert not fautes, "expressions Alpine refusées par la version CSP : " + ", ".join(fautes)
