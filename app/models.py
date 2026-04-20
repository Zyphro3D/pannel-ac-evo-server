from flask_login import UserMixin
from flask import current_app


class AdminUser(UserMixin):
    def __init__(self, role="admin"):
        self.id = role
        self.role = role

    @property
    def is_superadmin(self):
        return self.role == "superadmin"

    @staticmethod
    def check_credentials(username, password):
        cfg = current_app.config
        if username == cfg.get("SUPERADMIN_USERNAME") and password == cfg.get("SUPERADMIN_PASSWORD"):
            return "superadmin"
        if username == cfg["ADMIN_USERNAME"] and password == cfg["ADMIN_PASSWORD"]:
            return "admin"
        return None


from app import login_manager

@login_manager.user_loader
def load_user(user_id):
    if user_id in ("admin", "superadmin"):
        return AdminUser(role=user_id)
    return None
