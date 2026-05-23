import os
from pathlib import Path
from dotenv import load_dotenv
import base64

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


def _get_bool_env(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_list_env(name, default=None, required=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        values = list(default or [])
    else:
        values = [item.strip() for item in raw_value.split(",") if item.strip()]

    if required and not values:
        raise RuntimeError(f"{name} is required in production.")
    return values


def _get_env(name, default=None, required=False):
    value = os.getenv(name, default)
    if value is None:
        value = ""
    if required and not str(value).strip():
        raise RuntimeError(f"{name} is required in production.")
    return value


ENVIRONMENT = _get_env("ENVIRONMENT", "development").strip().lower()
if ENVIRONMENT not in {"development", "production"}:
    raise RuntimeError("ENVIRONMENT must be either 'development' or 'production'.")
IS_PRODUCTION = ENVIRONMENT == "production"

##################################################
# Environment configuration
# Required in production:
# - ENVIRONMENT=production
# - SECRET_KEY
# - ALLOWED_HOSTS
# - FRONTEND_URL
# - DB_NAME
# - DB_USER
# - DB_PASSWORD
# - CLOUD_SQL_CONNECTION_NAME
# - GS_BUCKET_NAME
# - RESEND_API_KEY
# - LALAMOVE_API_KEY
# - LALAMOVE_API_SECRET
# - MAYA_API_SECRET_KEY
# - MAYA_API_PUBLIC_KEY
# - MAYA_SANDBOX_BASE_URL
##################################################

SECRET_KEY = _get_env(
    "SECRET_KEY",
    default="django-insecure-default-key-change-me" if not IS_PRODUCTION else None,
    required=IS_PRODUCTION,
)
# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = _get_bool_env("DEBUG", default=not IS_PRODUCTION)
USE_GCS = True if IS_PRODUCTION else _get_bool_env("USE_GCS", default=False)

ALLOWED_HOSTS = _get_list_env(
    "ALLOWED_HOSTS",
    default=["127.0.0.1", "localhost", "raquel-washiest-heike.ngrok-free.dev"] if not IS_PRODUCTION else None,
    required=IS_PRODUCTION,
)

FRONTEND_URL = _get_env(
    "FRONTEND_URL",
    default="http://127.0.0.1:8001" if not IS_PRODUCTION else None,
    required=IS_PRODUCTION,
)
CORS_ALLOWED_ORIGINS = [FRONTEND_URL]
CSRF_TRUSTED_ORIGINS = [FRONTEND_URL, "https://raquel-washiest-heike.ngrok-free.dev"]

AUTH_COOKIE_SECURE = _get_bool_env("AUTH_COOKIE_SECURE", default=IS_PRODUCTION)
AUTH_COOKIE_SAMESITE = "Lax"

DB_NAME = _get_env("DB_NAME", default="weaveforward_db" if not IS_PRODUCTION else None, required=IS_PRODUCTION)
DB_USER = _get_env("DB_USER", default="root" if not IS_PRODUCTION else None, required=IS_PRODUCTION)
DB_PASSWORD = _get_env("DB_PASSWORD", default="" if not IS_PRODUCTION else None, required=IS_PRODUCTION)
CLOUD_SQL_CONNECTION_NAME = _get_env("CLOUD_SQL_CONNECTION_NAME", default=None, required=IS_PRODUCTION)
DB_HOST = _get_env("DB_HOST", default="127.0.0.1")
DB_PORT = _get_env("DB_PORT", default="3306")

CATALOG_CSV_PATH = _get_env("CATALOG_CSV_PATH", "backend/data/webscraped_data/webscraped_catalog_archive.csv")
RESEND_API_KEY = _get_env("RESEND_API_KEY", default=None, required=IS_PRODUCTION)
LALAMOVE_API_KEY = _get_env("LALAMOVE_API_KEY", default=None, required=IS_PRODUCTION)
LALAMOVE_API_SECRET = _get_env("LALAMOVE_API_SECRET", default=None, required=IS_PRODUCTION)
MAYA_API_SECRET_KEY = _get_env("MAYA_API_SECRET_KEY", default=None, required=IS_PRODUCTION)
MAYA_API_PUBLIC_KEY = _get_env("MAYA_API_PUBLIC_KEY", default=None, required=IS_PRODUCTION)
MAYA_SANDBOX_BASE_URL = _get_env(
    "MAYA_SANDBOX_BASE_URL",
    default="https://pg-sandbox.paymaya.com/payments/v1" if not IS_PRODUCTION else None,
    required=IS_PRODUCTION,
)
MAYA_SANDBOX_SECRET_BASIC_AUTH = f"Basic {base64.b64encode((MAYA_API_SECRET_KEY + ':').encode()).decode()}"
MAYA_SANDBOX_PUBLIC_BASIC_AUTH = f"Basic {base64.b64encode((MAYA_API_PUBLIC_KEY + ':').encode()).decode()}"

GS_BUCKET_NAME = _get_env('GS_BUCKET_NAME', default=None, required=IS_PRODUCTION)
GS_PROJECT_ID = _get_env('GS_PROJECT_ID')  # Optional, uses default cred project if not set
##################################################

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'django_filters',
    'backend',
]

if USE_GCS:
    INSTALLED_APPS.append('storages')

AUTH_USER_MODEL = 'backend.User'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.middleware.gzip.GZipMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

APPEND_SLASH = False

ROOT_URLCONF = 'WeaveForward_Backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'WeaveForward_Backend.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': DB_NAME,
        'USER': DB_USER,
        'PASSWORD': DB_PASSWORD,
    }
}

if CLOUD_SQL_CONNECTION_NAME:
    DATABASES['default']['HOST'] = f'/cloudsql/{CLOUD_SQL_CONNECTION_NAME}'
else:
    DATABASES['default']['HOST'] = DB_HOST
    DATABASES['default']['PORT'] = DB_PORT

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.BCryptPasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
CORS_ALLOW_CREDENTIALS = True

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

if USE_GCS:
    DEFAULT_FILE_STORAGE = 'storages.backends.gcloud.GoogleCloudStorage'
    GS_DEFAULT_ACL = None
    GS_QUERYSTRING_AUTH = False

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'backend.services.auth_service.CookieJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 10,
}

SIMPLE_JWT = {
    'UPDATE_LAST_LOGIN': False,

    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',

    'USER_ID_FIELD': 'user_id',
    'USER_ID_CLAIM': 'user_id',
    'JTI_CLAIM': 'jti',
}
