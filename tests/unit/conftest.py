"""Fixtures communes aux tests unitaires (pytest). Données entièrement synthétiques."""
import json
import os
import sys
from pathlib import Path

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# config.py exige ces variables à l'import : valeurs factices, uniquement pour les tests.
for _k, _v in (("SECRET_KEY", "test-secret-key"), ("ADMIN_PASSWORD", "test-admin"),
               ("SUPERADMIN_PASSWORD", "test-superadmin")):
    os.environ.setdefault(_k, _v)


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
