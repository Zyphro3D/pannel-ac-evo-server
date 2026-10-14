from app.services import csv_export


def test_formula_injection_is_neutralised():
    out = csv_export.to_csv(["a"], [["=1+1"], ["+cmd"], ["-2"], ["@x"], ["normal"], [None], [3]]).decode("utf-8-sig")
    lines = out.splitlines()
    assert lines[1:] == ["'=1+1", "'+cmd", "'-2", "'@x", "normal", '""', "3"]   # une cellule vide seule est citée par csv


def test_csv_has_bom_and_semicolon():
    raw = csv_export.to_csv(["x", "y"], [["a;b", "c"]])
    assert raw.startswith(b"\xef\xbb\xbf") and raw.decode("utf-8-sig").splitlines()[1] == '"a;b";c'


def test_admin_exports_need_admin_and_work(admin_client):
    assert admin_client.get("/export/drivers.csv").status_code == 200
    assert admin_client.get("/export/results.csv").status_code == 200
    assert admin_client.get("/export/fairplay.csv").status_code == 200
    anon = admin_client.application.test_client()
    assert anon.get("/export/drivers.csv").status_code == 302          # redirigé vers la connexion
    assert anon.get("/export/results.csv").status_code == 302
    assert anon.get("/results/999999/export.csv").status_code == 404


def test_audit_page_is_superadmin_only_and_exports(admin_client):
    assert admin_client.get("/admin/audit").status_code == 200
    r = admin_client.get("/admin/audit.csv")
    assert r.status_code == 200 and r.mimetype == "text/csv"
    assert admin_client.application.test_client().get("/admin/audit").status_code == 302


def test_health_and_backup_pages_render(admin_client):
    for url in ("/admin/health", "/admin/health.json", "/admin/backup"):
        r = admin_client.get(url)
        assert r.status_code == 200, url
    assert admin_client.application.test_client().get("/admin/health").status_code == 302
