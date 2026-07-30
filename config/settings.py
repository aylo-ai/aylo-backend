import os
import sys
import redis
from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta
from django.utils.translation import gettext_lazy as _
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv()

DEBUG: bool = os.environ.get("DEBUG") in ["True", "true"]

SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if DEBUG or "test" in sys.argv:
        SECRET_KEY = "django-insecure-dev-only-key-do-not-use-in-production"
    else:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured("SECRET_KEY environment variable is required when DEBUG is off")

ALLOWED_HOSTS = os.environ.get(
    "ALLOWED_HOSTS",
    ".aylo.uz,.repli.uz,localhost,127.0.0.1",
).split(",")

# Tests intentionally simulate outages (OpenAI down, Redis down, …) and the
# fail-soft code logs them. Silence logging during test runs so a green run
# reads green — only real test failures show up.
TESTING = "test" in sys.argv
if TESTING:
    import logging

    logging.disable(logging.CRITICAL)

AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT")


# Application definition

DEFAULT_APPS = [
    "modeltranslation",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

PACKAGES = [
    "rest_framework",
    "rest_framework_simplejwt",
    "rest_framework_simplejwt.token_blacklist",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    'django_celery_beat',
    "corsheaders",
    "django_filters",
    "telegram",
    "storages",
]
# Fully qualified so every module has exactly one importable path. The bare
# names used to work only because `apps/` was appended to sys.path, which made
# `shared.x` and `apps.shared.x` two distinct module objects — two copies of
# every module-level singleton (redis_client, conversation_service, agent, …).
# The app labels are unchanged (Django takes the last component), so migrations,
# db_table names and content types are unaffected.
INTERNAL_APPS = [
    "apps.assistant",
    "apps.integration",
    "apps.payment",
    "apps.shared",
    "apps.user",
    "apps.blog",
    "apps.landing",
    "apps.dashboard",
]

INSTALLED_APPS = DEFAULT_APPS + PACKAGES + INTERNAL_APPS

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
    ),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "10/minute",
        "landing_lead": "10/minute",
        "otp_send": "5/minute",
        "otp_verify": "10/minute",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Repli new brand AI system",
    "DESCRIPTION": "Repli.uz swagger docs (rest api service)",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "SCHEMA_PATH_PREFIX": r"/api/v1/",
}

if not DEBUG:
    SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ("apps.shared.permissions.IsSuperAdmin",)
    SPECTACULAR_SETTINGS["SERVE_AUTHENTICATION"] = (
        "rest_framework.authentication.BasicAuthentication",
    )


MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Reads Accept-Language and activates it for the request. A hand-rolled
    # `config.middleware.LanguageMiddleware` used to run ahead of this one and
    # called `activate()` then `deactivate()` *before* handing off to the view,
    # so the chosen language was thrown away on every request. It also read
    # `META["Accept-Language"]` instead of `META["HTTP_ACCEPT_LANGUAGE"]`, so it
    # never matched anything in the first place. Deleted — this does the job.
    # Must stay after SessionMiddleware and before CommonMiddleware.
    'django.middleware.locale.LocaleMiddleware',
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / 'apps' / 'shared' / 'addons' / 'templates',]
        ,
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


DATABASES = {
    "default": {
        "ENGINE": os.environ.get("DB_ENGINE"),
        "NAME": os.environ.get("DB_NAME"),
        "USER": os.environ.get("DB_USER"),
        "PASSWORD": os.environ.get("DB_PASSWORD"),
        "HOST": os.environ.get("DB_HOST"),
        "PORT": os.environ.get("DB_PORT"),
        "ATOMIC_REQUESTS": True,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Security Headers
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_HSTS_SECONDS = 3600

CORS_ORIGIN_ALLOW_ALL = False

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5500",
    "https://aylo.uz",
    "https://api.aylo.uz",
    "https://app.aylo.uz",
    "https://admin.aylo.uz",
    "https://dashboard.aylo.uz",
    "https://repli.uz",
    "https://app.repli.uz",
    "https://admin.repli.uz",
    "https://dashboard.repli.uz",
    "https://dev-app.repli.uz",
    "https://dev-api.repli.uz",
    "https://df04-82-215-100-92.ngrok-free.app",
]

CORS_ALLOW_METHODS = [
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
]

CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = [
    "accept",
    "authorization",
    "content-type",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
    "access-control-allow-origin",
    "access-control-allow-credentials",
]

CSRF_TRUSTED_ORIGINS = [
    "https://*.aylo.uz",
    "https://*.repli.uz",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "https://df04-82-215-100-92.ngrok-free.app",
]

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(days=7),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "VERIFYING_KEY": None,
    "AUDIENCE": None,
    "ISSUER": None,
    "JWK_URL": None,
    "LEEWAY": 0,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "AUTH_HEADER_NAME": "HTTP_AUTHORIZATION",
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "USER_AUTHENTICATION_RULE": "rest_framework_simplejwt.authentication.default_user_authentication_rule",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
    "TOKEN_TYPE_CLAIM": "token_type",
    "TOKEN_USER_CLASS": "rest_framework_simplejwt.models.TokenUser",
    "JTI_CLAIM": "jti",
    "SLIDING_TOKEN_REFRESH_EXP_CLAIM": "refresh_exp",
    "SLIDING_TOKEN_LIFETIME": timedelta(minutes=5),
    "SLIDING_TOKEN_REFRESH_LIFETIME": timedelta(days=1),
}

# The single source of truth for languages. There must be a matching
# `locale/<code>/LC_MESSAGES/django.po` for every entry — a code listed here
# without a catalog silently serves the Uzbek source strings instead.
# `ko` is Korean; the catalog lived under `kn` (which is Kannada) until the
# 2026-07-30 i18n pass, so `ko` clients got nothing at all.
LANGUAGES = [
    ('uz', _('Uzbek')),
    ('ru', _('Russian')),
    ('en', _('English')),
    ('kk', _('Kazakh')),
    ('ko', _('Korean')),
]

# Directory to store language files (translations)
LOCALE_PATHS = [
    os.path.join(BASE_DIR, 'locale')
]


# Default language
LANGUAGE_CODE = "uz-uz"

TIME_ZONE = "Asia/Tashkent"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"  # URL for serving static files
# # Directory for static files after collectstatic
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")


# # Media files (user-uploaded content)
MEDIA_URL = "/media/"  # URL for serving media files
MEDIA_ROOT = os.path.join(BASE_DIR, "media")  # Directory for storing media files

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "user.User"

REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
REDIS_HOST = os.environ.get("REDIS_HOST", default="localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB = int(os.environ.get("REDIS_DB", 0))
redis_connection = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    db=0,
)
REDIS_URL: str = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
# Celery settings
# CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
# CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True


# LOGGING = {
#     "version": 1,
#     "disable_existing_loggers": False,
#     "formatters": {
#         "default-formatter": {
#             "format": "[%(levelname)s] %(asctime)s %(filename)s:%(lineno)s:%(funcName)s: %(message)s",
#             "datefmt": "%m/%d/%Y %H:%M:%S",
#         },
#     },
#     "handlers": {
#         "console": {
#             "level": "DEBUG",
#             "class": "logging.StreamHandler",
#             "formatter": "default-formatter",
#         },
#     },
#     "loggers": {
#         "": {
#             "level": "WARNING",
#             "handlers": ["console"],
#         },
#         "django": {
#             "level": "ERROR",
#             "handlers": ["console"],
#             "propagate": False,
#         },
#         "django.request": {
#             "level": "ERROR",
#             "handlers": ["console"],
#             "propagate": False,
#         },
#         "api": {
#             "level": "DEBUG",
#             "handlers": ["console"],
#         },
#     },
# }

REDIS_DB: int = int(os.environ.get("REDIS_DB", default=0))
REDIS_HOST: str = os.environ.get("REDIS_HOST", default="localhost")
REDIS_PASSWORD: str = os.environ.get("REDIS_PASSWORD", default="")
REDIS_PORT: int = int(os.environ.get("REDIS_PORT", default=6379))


if REDIS_PASSWORD:
    CELERY_BROKER_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    CELERY_RESULT_BACKEND = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
else:
    CELERY_BROKER_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    CELERY_RESULT_BACKEND = f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
    
REDIS_CREDENTIALS: dict[str, str | int | bool] = {
    "db": REDIS_DB,
    "host": REDIS_HOST,
    "port": REDIS_PORT,
    "password": REDIS_PASSWORD,
    "decode_responses": True,  # NOTE: results won't be in BYTES format
}

PAYME_KEY = os.environ.get("PAYME_KEY")
PAYME_ID = os.environ.get("PAYME_ID")
PAYME_API_URL = os.environ.get("PAYME_API_URL", default="https://checkout.paycom.uz/api")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")

GOOGLE_GEMINI_API_KEY = os.environ.get("GOOGLE_GEMINI_API_KEY")

# Email settings
# Overridable so a local environment can print the OTP email to the console
# (`EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend`) instead of
# needing live Zoho SMTP credentials to exercise the email sign-up flow.
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = 'smtppro.zoho.com'
EMAIL_PORT = 465
EMAIL_USE_SSL = True

EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD")
DEFAULT_FROM_EMAIL = os.environ.get("EMAIL_HOST_USER")

# Instagram settings
INSTAGRAM_CLIENT_ID = os.environ.get("INSTAGRAM_CLIENT_ID")
INSTAGRAM_CLIENT_SECRET = os.environ.get("INSTAGRAM_CLIENT_SECRET")
INSTAGRAM_REDIRECT_URI = os.environ.get("INSTAGRAM_REDIRECT_URI")
INSTAGRAM_VERIFY_TOKEN = os.environ.get("INSTAGRAM_VERIFY_TOKEN", "")
INSTAGRAM_APP_SECRET = os.environ.get("INSTAGRAM_APP_SECRET", "")

DATA_UPLOAD_MAX_MEMORY_SIZE = 104857600  # 100 MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 104857600  # 100 MB


#AWS Bucket S3 Settings
AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
AWS_S3_CUSTOM_DOMAIN = os.environ.get("AWS_S3_CUSTOM_DOMAIN")

# File storage
AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME")
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME")



MEDIA_URL = '/media/'

STORAGES = {
    "default": {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

CELERY_BEAT_SCHEDULE = {
    'process-monthly-subscriptions': {
        'task': 'apps.payment.tasks.process_monthly_subscriptions',
        'schedule': crontab(minute=0, hour=0),  # Run every day at 00:00
    },
    'update-billz-products-hourly': {
        'task': 'apps.integration.tasks.update_billz_products_hourly',
        'schedule': crontab(minute=0),  # Run every hour at minute 0
    },
    'daily_statistics_assistant':{
        'task': 'apps.assistant.tasks.daily_statistics_assistant',
        'schedule': crontab(minute=0, hour=21),  # Run every day at 21:00
    },
    'process-follow-ups': {
        'task': 'apps.assistant.tasks.process_follow_ups',
        'schedule': crontab(minute='*/30'),  # Run every 30 minutes
    },
}

# Modeltranslation settings.
#
# This block used to redefine `LANGUAGES` — a second, plain-string copy that
# silently overrode the lazy one above and dropped Korean. It listed `ar` as
# well, for which no catalog and no translated field has ever existed. Both are
# gone: `LANGUAGES` is defined once, and modeltranslation follows it.
MODELTRANSLATION_DEFAULT_LANGUAGE = 'uz'

# Deliberately NOT `LANGUAGES`. These codes are database columns — `blog` and
# `payment` already carry migrated `*_ar` fields (see
# payment/migrations/0020_feature_name_ar_...). Dropping `ar` or adding `ko`
# here makes modeltranslation query columns that do not exist and demands a
# destructive migration, so the interface languages above and the translated
# model fields are allowed to differ until someone decides that explicitly.
MODELTRANSLATION_LANGUAGES = ('en', 'uz', 'ru', 'kk', 'ar')

# amoCRM OAuth. Read from the environment — these are live credentials and must
# never be committed. `AMOCRM_ACCESS_TOKEN` and the `BITRIX_*` pair used to sit
# here as literals with no reader anywhere in the tree; they were removed rather
# than migrated.
AMOCRM_CLIENT_ID = os.environ.get("AMOCRM_CLIENT_ID")
AMOCRM_SECRET_KEY = os.environ.get("AMOCRM_SECRET_KEY")

BASE_URL = os.environ.get("BASE_URL", "https://api.aylo.uz")

# Fail fast in production rather than serving a broken amoCRM OAuth flow that
# only reveals itself when a customer tries to connect their account.
if not DEBUG and not TESTING:
    _missing = [
        name for name in ("AMOCRM_CLIENT_ID", "AMOCRM_SECRET_KEY")
        if not globals()[name]
    ]
    if _missing:
        from django.core.exceptions import ImproperlyConfigured

        raise ImproperlyConfigured(
            f"Missing required environment variables: {', '.join(_missing)}"
        )

#Azure OpenAi settings
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
