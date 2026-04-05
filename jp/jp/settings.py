import os
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RUNNING_TESTS = "test" in sys.argv


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"true", "1", "yes", "on"}


DEBUG = _env_flag("DEBUG", True)


def _load_secret_key() -> str:
    env_secret = os.environ.get("DJANGO_SECRET_KEY", "").strip()
    if env_secret:
        return env_secret

    local_secret_path = BASE_DIR / ".django_secret_key"
    if local_secret_path.exists():
        return local_secret_path.read_text(encoding="utf-8").strip()

    generated_secret = secrets.token_urlsafe(50)
    try:
        local_secret_path.write_text(generated_secret, encoding="utf-8")
        return generated_secret
    except OSError:
        if DEBUG:
            return generated_secret

    raise RuntimeError("DJANGO_SECRET_KEY must be set when DEBUG is disabled.")


SECRET_KEY = _load_secret_key()

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
ALLOWED_HOSTS.extend(["testserver", "localhost", "127.0.0.1"])

RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f"https://{RENDER_EXTERNAL_HOSTNAME}")

ENABLE_HTTPS_SECURITY = _env_flag("DJANGO_ENABLE_HTTPS_SECURITY", bool(RENDER_EXTERNAL_HOSTNAME))

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = ENABLE_HTTPS_SECURITY
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = ENABLE_HTTPS_SECURITY
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = ENABLE_HTTPS_SECURITY
SECURE_HSTS_SECONDS = 31536000 if ENABLE_HTTPS_SECURITY else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = ENABLE_HTTPS_SECURITY
SECURE_HSTS_PRELOAD = ENABLE_HTTPS_SECURITY


INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'barber',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Add WhiteNoise only for deployment-style environments.
if ENABLE_HTTPS_SECURITY and not RUNNING_TESTS:
    try:
        import whitenoise  # noqa: F401
        MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
    except ImportError:
        pass

ROOT_URLCONF = 'jp.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'jp.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.0/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = os.environ.get('APP_TIME_ZONE', 'America/Toronto')

USE_I18N = True

USE_TZ = True

TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '')
BOOKSY_GLOBAL_URL = os.environ.get(
    'BOOKSY_GLOBAL_URL',
    'https://booksy.com/en-ca/21963_jp-barber-studio_barbershop_870806_mississauga#ba_s=sh_1',
)
BOOKSY_WIDGET_SCRIPT_URL = os.environ.get(
    'BOOKSY_WIDGET_SCRIPT_URL',
    'https://booksy.com/widget/code.js?id=21963&country=ca&lang=en',
)
GOOGLE_BOOKING_URL = os.environ.get('GOOGLE_BOOKING_URL', '')


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.0/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise for serving static files in production
if ENABLE_HTTPS_SECURITY and not RUNNING_TESTS:
    try:
        import whitenoise  # noqa: F401
        STORAGES = {
            "staticfiles": {
                "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
            },
        }
    except ImportError:
        pass

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
