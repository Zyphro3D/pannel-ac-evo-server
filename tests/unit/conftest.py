"""Fixtures pytest partagées.

Les env vars sont fixées AVANT tout import de `app` ou `config` : le module
`config.py` valide SECRET_KEY/ADMIN_PASSWORD/SUPERADMIN_PASSWORD à l'import
(_required_env lève sinon), donc conftest.py doit les poser en premier —
pytest importe les conftest.py d'un dossier avant les fichiers de test qu'il contient.

DATABASE_URL est forcé vers un fichier temporaire à chaque session de tests :
jamais la vraie DB du panel (panel_data/ace_evo.db), même si un .env réel
est monté dans le conteneur.
"""
import os
import tempfile

_TEST_DB_FD, _TEST_DB_PATH = tempfile.mkstemp(suffix=".db", prefix="ace_evo_test_")
os.close(_TEST_DB_FD)

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin-pw")
os.environ.setdefault("SUPERADMIN_USERNAME", "superadmin")
os.environ.setdefault("SUPERADMIN_PASSWORD", "test-superadmin-pw")
os.environ.setdefault("RESULTS_INGEST_SECRET", "test-ingest-secret")
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def app():
    from app import create_app
    flask_app = create_app()
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield flask_app
    try:
        os.remove(_TEST_DB_PATH)
    except OSError:
        pass


@pytest.fixture()
def client(app):
    return app.test_client()
