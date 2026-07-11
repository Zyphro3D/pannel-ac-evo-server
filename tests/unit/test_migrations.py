"""Tests pour les migrations DB (_migrate_* appelées dans create_app()).

Le fixture `app` construit déjà une DB neuve via create_app() (voir conftest.py) —
ces tests vérifient surtout l'IDEMPOTENCE : rejouer les migrations sur une DB
qui les a déjà appliquées ne doit jamais lever, puisque c'est ce qui se passe
à chaque redémarrage du panel sur une installation existante.
"""
import sqlalchemy as sa


def test_create_app_migrates_a_fresh_db_without_error(app):
    """Le fixture app() a déjà tourné avec succès pour arriver ici — sanity check explicite."""
    with app.app_context():
        from app.services.database import db
        assert db.engine is not None


def test_new_index_on_event_registration_driver_id_exists(app):
    """Régression pour AUDIT_v1.9.1.md item 8 : EventRegistration.driver_id doit être indexé."""
    with app.app_context():
        from app.services.database import db
        with db.engine.connect() as conn:
            row = conn.execute(sa.text(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='ix_event_registration_driver_id'"
            )).fetchone()
        assert row is not None


def test_migrations_are_idempotent(app):
    """Rejouer toutes les migrations sur une DB déjà migrée ne doit jamais lever
    (c'est ce qui se passe à chaque redémarrage du panel sur une install existante)."""
    with app.app_context():
        from app.services.database import db
        from app.routes.admin import (
            _migrate_db, _migrate_indexes, _migrate_server_discord,
            _migrate_server_http_port, _migrate_event_server_id,
            _migrate_car_meta_props, _migrate_result_hash,
            _migrate_driver_steam_id, _migrate_admin_account_extra,
            _migrate_driver_email_confirmation,
        )
        _migrate_db(db)
        _migrate_indexes(db)
        _migrate_server_discord(db)
        _migrate_server_http_port(db)
        _migrate_event_server_id(db)
        _migrate_car_meta_props(db)
        _migrate_result_hash(db)
        _migrate_driver_steam_id(db)
        _migrate_admin_account_extra(db)
        _migrate_driver_email_confirmation(db)


def test_core_tables_exist(app):
    with app.app_context():
        from app.services.database import db
        inspector = sa.inspect(db.engine)
        tables = set(inspector.get_table_names())
        for expected in ("event", "driver", "event_registration", "server",
                         "session_result", "admin_account"):
            assert expected in tables


def test_admin_and_superadmin_accounts_are_seeded(app):
    with app.app_context():
        from app.models import AdminAccount
        usernames = {a.username for a in AdminAccount.query.all()}
        assert app.config["ADMIN_USERNAME"] in usernames
        assert app.config["SUPERADMIN_USERNAME"] in usernames
