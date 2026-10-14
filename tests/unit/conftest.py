"""Fixtures communes aux tests unitaires (pytest). Données entièrement synthétiques."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# config.py exige ces variables à l'import : valeurs factices, uniquement pour les tests.
_TMP = tempfile.mkdtemp(prefix="panel-tests-")
for _k, _v in (("SECRET_KEY", "test-secret-key"), ("ADMIN_PASSWORD", "test-admin"),
               ("SUPERADMIN_PASSWORD", "test-superadmin"), ("SUPERADMIN_USERNAME", "superadmin"),
               ("DATABASE_URL", "sqlite:///" + _TMP + "/test.db"), ("ACESERVER_DIR", _TMP),
               ("CONFIGS_DIR", _TMP + "/configs")):
    os.environ.setdefault(_k, _v)
os.makedirs(_TMP + "/configs", exist_ok=True)


@pytest.fixture
def cars_app(tmp_path):
    """Mini application Flask avec un cars.json de test (sans base de données)."""
    cars = {"cars": [
        {"name": "preset_m4gt3_mech_1", "display_name": "BMW M4 GT3 - Standard"},
        {"name": "preset_cup_bop_1", "display_name": "Porsche 911 GT3 Cup - BOP Carrera Cup"},
        {"name": "preset_sans_classe", "display_name": "Voiture Sans Classe"},
    ]}
    cars_path = tmp_path / "cars.json"
    cars_path.write_text(json.dumps(cars), encoding="utf-8")
    app = Flask(__name__)
    app.config["CARS_JSON_PATH"] = str(cars_path)
    app.config["MODS_DIR"] = str(tmp_path / "mods")
    return app


@pytest.fixture(scope="module")
def admin_client():
    """Application complète (base SQLite temporaire) avec un super-admin connecté."""
    import app as app_pkg
    import app.routes.admin as admin_routes
    # settings.json vit à côté du code (data/) : on le détourne vers un dossier temporaire pour que les
    # tests n'écrivent ni ne lisent jamais les vrais réglages
    tmp_settings = Path(_TMP) / "settings.json"
    app_pkg._SETTINGS_PATH = tmp_settings
    admin_routes._SETTINGS_PATH = tmp_settings
    from app import create_app, limiter
    app = create_app()
    app.config["WTF_CSRF_ENABLED"] = False
    limiter.enabled = False
    client = app.test_client()
    client.post("/login", data={"username": "superadmin", "password": os.environ["SUPERADMIN_PASSWORD"]})
    client.app = app
    return client
