from django.apps import AppConfig


class BackendConfig(AppConfig):
    name = 'backend'


class FrameworkTableBlocker:
    blocked_app_labels = {
        "admin",
        "auth",
        "sessions",
        "token_blacklist",
    }

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label in self.blocked_app_labels:
            return False
        return None
