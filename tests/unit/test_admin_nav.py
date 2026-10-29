"""Menu Admin (grand menu, panneau mobile) et recherche « Où régler… ? »."""
import json
import re

from app.services import admin_nav


def _index(page):
    m = re.search(r'<script type="application/json" id="admin-find-data">(.*?)</script>', page, re.S)
    return json.loads(m.group(1))


def test_menu_en_4_groupes_avec_explications(admin_client):
    page = admin_client.get("/servers").get_data(as_text=True)
    for title in ("Serveur", "Courses et pilotes", "Contenu du jeu", "Panel"):
        assert f'<div class="admin-grp">{title} <b>' in page
    assert "Réglages du serveur<small>nom, ports, mots de passe, Discord</small>" in page
    assert "Où régler… ?" in page and "admin-nav.js" in page


def test_chaque_lien_de_la_recherche_mene_a_une_page_et_une_ancre_existantes(admin_client):
    page = admin_client.get("/servers").get_data(as_text=True)
    index = _index(page)
    assert len(index) >= 30
    pages = {}
    for entry in index:
        path, _, anchor = entry["url"].partition("#")
        if path not in pages:
            resp = admin_client.get(path, follow_redirects=True)   # /server renvoie vers l'installation sans serveur de jeu
            assert resp.status_code == 200, (entry["label"], path, resp.status_code)
            pages[path] = resp.get_data(as_text=True)
        if anchor:
            assert f'id="{anchor}"' in pages[path], (entry["label"], anchor)


def test_admin_simple_ne_voit_pas_les_reglages_superadmin(admin_client):
    with admin_client.app.test_request_context("/"):
        groups = {g["id"]: [i["label"] for i in g["items"]] for g in admin_nav.admin_menu(False, "GT3")}
        labels = [e["label"] for e in admin_nav.settings_index(False)]
    assert "Réglages du serveur" not in groups["server"] and "Serveurs" not in groups["panel"]
    assert groups["panel"] == ["Santé et journal"]
    assert not any("Webhooks" in label for label in labels)


def test_ancien_onglet_evenement_redirige(admin_client):
    resp = admin_client.get("/server?view=events")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/events")
