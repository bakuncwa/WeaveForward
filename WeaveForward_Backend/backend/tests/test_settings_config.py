import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import TestCase


BACKEND_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_IMPORT = "import json; import WeaveForward_Backend.settings as s; print(json.dumps({"
SETTINGS_IMPORT += "'DEBUG': s.DEBUG, "
SETTINGS_IMPORT += "'AUTH_COOKIE_SECURE': s.AUTH_COOKIE_SECURE, "
SETTINGS_IMPORT += "'AUTH_COOKIE_SAMESITE': s.AUTH_COOKIE_SAMESITE, "
SETTINGS_IMPORT += "'ALLOWED_HOSTS': s.ALLOWED_HOSTS, "
SETTINGS_IMPORT += "'CORS_ALLOWED_ORIGINS': s.CORS_ALLOWED_ORIGINS, "
SETTINGS_IMPORT += "'CSRF_TRUSTED_ORIGINS': s.CSRF_TRUSTED_ORIGINS, "
SETTINGS_IMPORT += "'USE_GCS': s.USE_GCS"
SETTINGS_IMPORT += "}))"


class SettingsConfigTest(TestCase):
    maxDiff = None

    def _base_env(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(BACKEND_ROOT)
        env["PYTHON_DOTENV_DISABLED"] = "1"
        return env

    def _production_env(self):
        env = self._base_env()
        env.update(
            {
                "ENVIRONMENT": "production",
                "SECRET_KEY": "prod-secret",
                "ALLOWED_HOSTS": "api.example.com",
                "DB_NAME": "prod_db",
                "DB_USER": "prod_user",
                "DB_PASSWORD": "prod_password",
                "CLOUD_SQL_CONNECTION_NAME": "project:region:instance",
                "GS_BUCKET_NAME": "prod-bucket",
                "RESEND_API_KEY": "resend-key",
                "LALAMOVE_API_KEY": "lalamove-key",
                "LALAMOVE_API_SECRET": "lalamove-secret",
                "MAYA_API_SECRET_KEY": "maya-secret",
                "MAYA_API_PUBLIC_KEY": "maya-public",
                "MAYA_SANDBOX_BASE_URL": "https://maya.example.com/payments/v1",
            }
        )
        for key in ("DEBUG", "AUTH_COOKIE_SECURE", "DB_HOST", "DB_PORT", "USE_GCS"):
            env.pop(key, None)
        return env

    def _development_env(self):
        env = self._base_env()
        env["ENVIRONMENT"] = "development"
        for key in (
            "SECRET_KEY",
            "DEBUG",
            "ALLOWED_HOSTS",
            "AUTH_COOKIE_SECURE",
            "DB_NAME",
            "DB_USER",
            "DB_PASSWORD",
            "DB_HOST",
            "DB_PORT",
            "CLOUD_SQL_CONNECTION_NAME",
            "RESEND_API_KEY",
            "LALAMOVE_API_KEY",
            "LALAMOVE_API_SECRET",
            "MAYA_API_SECRET_KEY",
            "MAYA_API_PUBLIC_KEY",
            "MAYA_SANDBOX_BASE_URL",
            "GS_BUCKET_NAME",
            "USE_GCS",
        ):
            env.pop(key, None)
        return env

    def _import_settings(self, env):
        return subprocess.run(
            [sys.executable, "-c", SETTINGS_IMPORT],
            cwd=BACKEND_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )

    def _assert_import_error(self, env, expected_text):
        result = self._import_settings(env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(expected_text, result.stderr)



    def test_production_requires_secret_key(self):
        env = self._production_env()
        env["SECRET_KEY"] = ""
        self._assert_import_error(env, "SECRET_KEY is required in production.")

    def test_production_requires_allowed_hosts(self):
        env = self._production_env()
        env["ALLOWED_HOSTS"] = ""
        self._assert_import_error(env, "ALLOWED_HOSTS is required in production.")

    def test_frontend_url_is_not_required(self):
        env = self._production_env()
        result = self._import_settings(env)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

        payload = json.loads(result.stdout)
        self.assertEqual(payload["CORS_ALLOWED_ORIGINS"], [])
        self.assertEqual(payload["CSRF_TRUSTED_ORIGINS"], [])

    def test_production_requires_db_name(self):
        env = self._production_env()
        env["DB_NAME"] = ""
        self._assert_import_error(env, "DB_NAME is required in production.")

    def test_production_requires_db_user(self):
        env = self._production_env()
        env["DB_USER"] = ""
        self._assert_import_error(env, "DB_USER is required in production.")

    def test_production_requires_db_password(self):
        env = self._production_env()
        env["DB_PASSWORD"] = ""
        self._assert_import_error(env, "DB_PASSWORD is required in production.")

    def test_production_requires_cloud_sql_connection_name(self):
        env = self._production_env()
        env["CLOUD_SQL_CONNECTION_NAME"] = ""
        self._assert_import_error(env, "CLOUD_SQL_CONNECTION_NAME is required in production.")

    def test_production_requires_gcs_bucket_name(self):
        env = self._production_env()
        env["GS_BUCKET_NAME"] = ""
        self._assert_import_error(env, "GS_BUCKET_NAME is required in production.")

    def test_production_requires_resend_api_key(self):
        env = self._production_env()
        env["RESEND_API_KEY"] = ""
        self._assert_import_error(env, "RESEND_API_KEY is required in production.")

    def test_production_requires_lalamove_api_key(self):
        env = self._production_env()
        env["LALAMOVE_API_KEY"] = ""
        self._assert_import_error(env, "LALAMOVE_API_KEY is required in production.")

    def test_production_requires_lalamove_api_secret(self):
        env = self._production_env()
        env["LALAMOVE_API_SECRET"] = ""
        self._assert_import_error(env, "LALAMOVE_API_SECRET is required in production.")

    def test_production_requires_maya_secret_key(self):
        env = self._production_env()
        env["MAYA_API_SECRET_KEY"] = ""
        self._assert_import_error(env, "MAYA_API_SECRET_KEY is required in production.")

    def test_production_requires_maya_public_key(self):
        env = self._production_env()
        env["MAYA_API_PUBLIC_KEY"] = ""
        self._assert_import_error(env, "MAYA_API_PUBLIC_KEY is required in production.")

    def test_production_requires_maya_base_url(self):
        env = self._production_env()
        env["MAYA_SANDBOX_BASE_URL"] = ""
        self._assert_import_error(env, "MAYA_SANDBOX_BASE_URL is required in production.")
