"""Formulaire « Ajouter un serveur » : ports proposés libres."""


def test_ports_proposes_apres_ceux_du_serveur_principal(admin_client):
    page = admin_client.get("/servers").get_data(as_text=True)
    assert 'name="tcp_port" class="form-control" value="9701"' in page
    assert 'name="http_port" class="form-control" value="8082"' in page
