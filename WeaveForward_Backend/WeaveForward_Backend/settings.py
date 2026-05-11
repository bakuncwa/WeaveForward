import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv
import base64

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-default-key-change-me')
# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.getenv('DEBUG', 'True') == 'True'
USE_GCS = os.getenv('USE_GCS', 'False') == 'True'

ALLOWED_HOSTS = ['*']

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
        'NAME': os.getenv('DB_NAME', 'weaveforward_db'),
        'USER': os.getenv('DB_USER', 'root'),
        'PASSWORD': os.getenv('DB_PASSWORD', ''),
    }
}

# If running on GCP Cloud Run, connect via Unix Socket
if os.getenv('CLOUD_SQL_CONNECTION_NAME'):
    DATABASES['default']['HOST'] = f'/cloudsql/{os.getenv("CLOUD_SQL_CONNECTION_NAME")}'
else:
    DATABASES['default']['HOST'] = os.getenv('DB_HOST', '127.0.0.1')
    DATABASES['default']['PORT'] = os.getenv('DB_PORT', '3306')

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.BCryptPasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.ScryptPasswordHasher',
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

# Environment-based settings
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:8001")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
CATALOG_CSV_PATH = os.getenv("CATALOG_CSV_PATH", "backend/data/webscraped_data/webscraped_catalog_archive.csv")

MAYA_SANDBOX_BASE_URL = os.getenv("MAYA_SANDBOX_BASE_URL", "https://pg-sandbox.paymaya.com/payments/v1")

MAYA_SANDBOX_SECRET_BASIC_AUTH = f"Basic {base64.b64encode((os.getenv('MAYA_API_SECRET_KEY', '') + ':').encode()).decode()}"
MAYA_SANDBOX_PUBLIC_BASIC_AUTH = f"Basic {base64.b64encode((os.getenv('MAYA_API_PUBLIC_KEY', '') + ':').encode()).decode()}"

CORS_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOWED_ORIGINS",
        f"{FRONTEND_URL},http://127.0.0.1:8001,http://localhost:8001",
    ).split(",")
    if origin.strip()
]

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CSRF_TRUSTED_ORIGINS",
        f"{FRONTEND_URL},http://127.0.0.1:8001,http://localhost:8001",
    ).split(",")
    if origin.strip()
]

AUTH_ACCESS_COOKIE_NAME = os.getenv("AUTH_ACCESS_COOKIE_NAME", "access_token")
AUTH_REFRESH_COOKIE_NAME = os.getenv("AUTH_REFRESH_COOKIE_NAME", "refresh_token")
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "False") == "True"
AUTH_COOKIE_SAMESITE = os.getenv("AUTH_COOKIE_SAMESITE", "Lax")
AUTH_COOKIE_DOMAIN = os.getenv("AUTH_COOKIE_DOMAIN") or None
AUTH_COOKIE_PATH = os.getenv("AUTH_COOKIE_PATH", "/")
CORS_ALLOW_CREDENTIALS = True

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

if USE_GCS:
    DEFAULT_FILE_STORAGE = 'storages.backends.gcloud.GoogleCloudStorage'
    GS_BUCKET_NAME = os.getenv('GS_BUCKET_NAME')
    GS_PROJECT_ID = os.getenv('GS_PROJECT_ID') # Optional, uses default cred project if not set
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

AUTH_ACCESS_TOKEN_LIFETIME = timedelta(minutes=60)
AUTH_REFRESH_TOKEN_LIFETIME = timedelta(days=1)
AUTH_ACCESS_COOKIE_MAX_AGE = int(AUTH_ACCESS_TOKEN_LIFETIME.total_seconds())
AUTH_REFRESH_COOKIE_MAX_AGE = int(AUTH_REFRESH_TOKEN_LIFETIME.total_seconds())

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': AUTH_ACCESS_TOKEN_LIFETIME,
    'REFRESH_TOKEN_LIFETIME': AUTH_REFRESH_TOKEN_LIFETIME,
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': False,

    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',

    'USER_ID_FIELD': 'user_id',
    'USER_ID_CLAIM': 'user_id',

    'JTI_CLAIM': 'jti',
}
