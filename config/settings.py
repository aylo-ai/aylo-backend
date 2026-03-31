import os
import sys
import redis
from pathlib import Path
from dotenv import load_dotenv
from datetime import timedelta
from django.utils.translation import gettext_lazy as _
from openai import AzureOpenAI
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(os.path.join(BASE_DIR, "apps"))
load_dotenv()

SECRET_KEY = os.environ.get("SECRET_KEY", "django-insecure-j_27^f$x$3_q^)-3vn6!ps*9apa$nshm)202rq98y^fhf+ydz=")
DEBUG: bool = os.environ.get("DEBUG") in ["True", "true"]

ALLOWED_HOSTS = ["*"]

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
INTERNAL_APPS = [
    "assistant",
    "integration",
    "payment",
    "shared",
    "user",
    "blog",
    "landing",
    "dashboard",
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
    "SCHEMA_PATH_PREFIX": r"/api/",
}

if not DEBUG:
    SPECTACULAR_SETTINGS["SERVE_PERMISSIONS"] = ("apps.shared.permissions.IsSuperAdmin",)
    SPECTACULAR_SETTINGS["SERVE_AUTHENTICATION"] = (
        "rest_framework.authentication.BasicAuthentication",
    )


MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "config.middleware.LanguageMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    'django.middleware.locale.LocaleMiddleware',  # Enables locale support
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

CORS_ALLOWED_HEADERS = [
    'content-type',
    'authorization',
    'x-requested-with',
    'accept',
    'origin',
    'accept-language',
]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:5500",
    "https://repli.uz",
    "https://app.repli.uz",
    "https://admin.repli.uz",
    "https://dashboard.repli.uz",
    "https://dev-app.repli.uz",
    "https://dev-api.repli.uz",
]

CORS_ALLOWED_METHODS = [
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
    "https://*.repli.uz",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
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

LANGUAGES = [
    ('en', _('English')),
    ('kk', _('Kazakh')),
    ('ru', _('Russian')),
    ('uz', _('Uzbek')),
    ('kn', _('Korean')),
    ('ar', _('Arabic')),
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


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default-formatter": {
            "format": "[%(levelname)s] %(asctime)s %(filename)s:%(lineno)s:%(funcName)s: %(message)s",
            "datefmt": "%m/%d/%Y %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "default-formatter",
        },
    },
    "loggers": {
        "": {
            "level": "WARNING",
            "handlers": ["console"],
        },
        "django": {
            "level": "ERROR",
            "handlers": ["console"],
            "propagate": False,
        },
        "django.request": {
            "level": "ERROR",
            "handlers": ["console"],
            "propagate": False,
        },
        "api": {
            "level": "DEBUG",
            "handlers": ["console"],
        },
    },
}

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

client = AzureOpenAI(api_key=OPENAI_API_KEY,
                     azure_endpoint=AZURE_OPENAI_ENDPOINT,
                     api_version="2024-05-01-preview")

GOOGLE_GEMINI_API_KEY = os.environ.get("GOOGLE_GEMINI_API_KEY")

# Email settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
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
INSTAGRAM_VERIFY_TOKEN = os.environ.get("INSTAGRAM_VERIFY_TOKEN", "wqbm2DoK5zfsF28Qb82Z")
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

# Modeltranslation settings
MODELTRANSLATION_DEFAULT_LANGUAGE = 'uz'

LANGUAGES = (
    ('en', 'English'),
    ('uz', 'Uzbek'),
    ('ru', 'Russian'),
    ('kk', 'Kazakh'),
    ('ar', 'Arabic'),
)
MODELTRANSLATION_LANGUAGES = ('en', 'uz', 'ru', 'kk', 'ar')


import sentry_sdk # Sentry SDK for error tracking and monitoring

# sentry_sdk.init(
#     dsn="https://cb6c7ba11d9da224011674295fef19a0@o4506302611980288.ingest.us.sentry.io/4510062349189120",
#     send_default_pii=True,
# )

BITRIX_CLIENT_ID='local.68fa1c012ca095.04783670'
BITRIX_CLIENT_KEY='8Jpee3uOJnVgQQzBNtHmzqhWufqxIfm7fzjiohFjK3RS2cpqqP'

AMOCRM_CLIENT_ID='f49eee4a-598e-406c-9111-8ad3f1194230'
AMOCRM_SECRET_KEY='pGaFSICclVG5i7HDlgzkaoChwitZXZHW5ZP5fxC6nYmHIoUgIxovgFAJ79v89lgH'
AMOCRM_ACCESS_TOKEN='eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsImp0aSI6Ijg2YThiMGIzZjJlMWY5MmM5ZjVjYjRjYTVjYTc5ZGQ0YzQxNGU0Yzk0Zjc0YjJhNTY2OTE2YTJhNGEzMjk0MDJjY2E0ZTQ4MDRhNGNjYWExIn0.eyJhdWQiOiJmNDllZWU0YS01OThlLTQwNmMtOTExMS04YWQzZjExOTQyMzAiLCJqdGkiOiI4NmE4YjBiM2YyZTFmOTJjOWY1Y2I0Y2E1Y2E3OWRkNGM0MTRlNGM5NGY3NGIyYTU2NjkxNmEyYTRhMzI5NDAyY2NhNGU0ODA0YTRjY2FhMSIsImlhdCI6MTc2MTIyNzE0MCwibmJmIjoxNzYxMjI3MTQwLCJleHAiOjE5MDIyNjg4MDAsInN1YiI6Ijk4NTM3OTgiLCJncmFudF90eXBlIjoiIiwiYWNjb3VudF9pZCI6MzI3MzE3MjIsImJhc2VfZG9tYWluIjoiYW1vY3JtLnJ1IiwidmVyc2lvbiI6Miwic2NvcGVzIjpbImNybSIsImZpbGVzIiwiZmlsZXNfZGVsZXRlIiwibm90aWZpY2F0aW9ucyIsInB1c2hfbm90aWZpY2F0aW9ucyJdLCJoYXNoX3V1aWQiOiIxNDI4MjVhZC1iYjcyLTRkZTAtYTY5MS0wODlmYTY5OWRiNGQiLCJ1c2VyX2ZsYWdzIjowLCJhcGlfZG9tYWluIjoiYXBpLWIuYW1vY3JtLnJ1In0.KfBz6OawRPwoOQ2XukHpLdByKEYBoO9bgr3SDGfa84ooF1vya6gRsHKWGAAdMQTIuJwzwZ55e4anHYJbsfXC7vJh71lnyE5zHNhWLQUS4gF9O6wuj9jku51oN7fYG5Uk08Z09bUBLGbizBLvGi8x_sycX8hm92gjx4-6kXZhys38yz6J94-GZUfrItHEd38Y0IxdE4PxQrevKFbP2AJB51t-sRUNLkPQw4GOPV7PeumPcpMEoqSJciiEHMNt0MzC4dyAHAwIdwHzxthRGg3MDz3PgzWrNZDQK_Nd5JKzsRG0oeBeRum3Ckk7Br5CEqAXoiHDhbc2C3zVrSnmtoi0dg'
BASE_URL='https://api.repli.uz'

#Azure OpenAi settings
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")