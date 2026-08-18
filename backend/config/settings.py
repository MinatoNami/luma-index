"""
Django settings for LumaIndex.

Everything environment-specific is read from the process environment so the
same image runs in development and production. See `.env.example` for the
full list of variables and what happens when they are wrong.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Environment helpers
# --------------------------------------------------------------------------- #

def env(key: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(key, default)
    if required and not value:
        raise RuntimeError(
            f"Required environment variable {key} is unset. "
            f"Copy .env.example to .env and fill it in."
        )
    return value or ""


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def env_list(key: str, default: str = "") -> list[str]:
    raw = os.environ.get(key, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------- #
# Core
# --------------------------------------------------------------------------- #

DEBUG = env_bool("DJANGO_DEBUG", False)

# In DEBUG we tolerate a throwaway key so `manage.py` works without a .env;
# in production an unset key is a hard failure rather than a silent weak default.
SECRET_KEY = env("DJANGO_SECRET_KEY", "insecure-development-key" if DEBUG else None,
                 required=not DEBUG)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,backend")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

PUBLIC_ORIGIN = env("LUMA_PUBLIC_ORIGIN", "http://localhost:8080")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "accounts",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "lumaindex"),
        "USER": env("POSTGRES_USER", "lumaindex"),
        "PASSWORD": env("POSTGRES_PASSWORD", "lumaindex" if DEBUG else None,
                        required=not DEBUG),
        "HOST": env("POSTGRES_HOST", "postgres"),
        "PORT": env("POSTGRES_PORT", "5432"),
        # Reuse connections between requests; 0 would reconnect on every request.
        "CONN_MAX_AGE": env_int("POSTGRES_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
    }
}


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
# Throttle counters live in the cache, so the cache has to be shared. Django's
# default LocMemCache is per-process: with N gunicorn workers a "10/min" limit
# is really 10*N, and every counter resets on deploy. A database cache is
# correct across workers and restarts, and keeps Redis out of the stack until
# an async workload actually justifies it (PRD §4, §36).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "lumaindex_cache",
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 10000, "CULL_FREQUENCY": 3},
    }
}


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/login"

# Reset links expire in an hour. Django's 3-day default is generous for an
# instance whose mail may sit in a log file.
PASSWORD_RESET_TIMEOUT = env_int("LUMA_PASSWORD_RESET_TIMEOUT", 3600)

# PRD non-goal: no open public registration unless explicitly enabled.
REGISTRATION_ENABLED = env_bool("LUMA_REGISTRATION_ENABLED", False)

# Include the resolved client address in authentication failure logs. Use it
# to confirm LUMA_NUM_PROXIES is right on a new deployment (PRD §41).
LOG_CLIENT_IP = env_bool("LUMA_LOG_CLIENT_IP", False)


# --------------------------------------------------------------------------- #
# Sessions, cookies and CSRF
# --------------------------------------------------------------------------- #
# Nuxt and Django are served from one origin behind Caddy, so SameSite=Lax is
# both sufficient and the safest default. Do not relax this to None without
# understanding that it makes the session cookie cross-site.

SESSION_COOKIE_NAME = "lumaindex_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SESSION_COOKIE_SECURE", not DEBUG)
SESSION_COOKIE_AGE = env_int("DJANGO_SESSION_COOKIE_AGE", 60 * 60 * 24 * 14)

# Readable by JS on purpose: the SPA echoes it back in the X-CSRFToken header.
# The session cookie above is the one that must stay HttpOnly.
CSRF_COOKIE_NAME = "lumaindex_csrftoken"
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = env_bool("DJANGO_CSRF_COOKIE_SECURE", not DEBUG)

# Caddy terminates TLS and forwards X-Forwarded-Proto; without this Django
# thinks every request is plain HTTP and refuses to set Secure cookies.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)


# --------------------------------------------------------------------------- #
# Django REST Framework
# --------------------------------------------------------------------------- #

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    # How many proxies sit in front of Django. This is a security setting, not
    # a tuning knob: left at DRF's default of None, throttles key on the whole
    # client-supplied X-Forwarded-For string, so an attacker varying that header
    # gets an unlimited number of fresh rate-limit buckets.
    #
    #   2 = tailscale serve -> caddy -> django   (the deployed topology)
    #   1 = caddy -> django                      (compose.dev.yaml)
    #
    # Verify with LUMA_LOG_CLIENT_IP=True and a failed login: the logged
    # client_ip must be the real client address, not a proxy's.
    "NUM_PROXIES": env_int("LUMA_NUM_PROXIES", 2),
    # Deny by default. Every public endpoint must opt out explicitly — the PRD
    # requires authorization to be enforced server-side, and a permissive
    # default is how that requirement quietly stops being true.
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # PRD §32: rate-limit authentication.
        # `auth` is per client address; `login_email` is per targeted account,
        # so credential stuffing against one user is capped even if proxy
        # configuration ever makes the address unreliable.
        "auth": env("LUMA_THROTTLE_AUTH", "10/min"),
        "login_email": env("LUMA_THROTTLE_LOGIN_EMAIL", "5/min"),
    },
    "UNAUTHENTICATED_USER": "django.contrib.auth.models.AnonymousUser",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "LumaIndex API",
    "DESCRIPTION": "Self-hosted multi-user PDF ebook reader.",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}


# --------------------------------------------------------------------------- #
# Email (password reset)
# --------------------------------------------------------------------------- #

if env("LUMA_EMAIL_BACKEND", "console") == "smtp":
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = env("EMAIL_HOST", required=True)
    EMAIL_PORT = env_int("EMAIL_PORT", 587)
    EMAIL_HOST_USER = env("EMAIL_HOST_USER")
    EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
    EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "lumaindex@localhost")


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #

PDF_CACHE_DIR = Path(env("LUMA_PDF_CACHE_DIR", str(BASE_DIR / "data" / "pdf-cache")))
THUMBNAIL_DIR = Path(env("LUMA_THUMBNAIL_DIR", str(BASE_DIR / "data" / "thumbnails")))
PDF_CACHE_MAX_BYTES = env_int("LUMA_PDF_CACHE_MAX_BYTES", 10 * 1024**3)

# Admin static files only. Never point this at PDF_CACHE_DIR — cached PDFs must
# be served through the authorization boundary, never as static content.
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}


# --------------------------------------------------------------------------- #
# Encryption of provider credentials
# --------------------------------------------------------------------------- #

FIELD_ENCRYPTION_KEY = env("LUMA_FIELD_ENCRYPTION_KEY")
FIELD_ENCRYPTION_KEYS_LEGACY = env_list("LUMA_FIELD_ENCRYPTION_KEYS_LEGACY")


# --------------------------------------------------------------------------- #
# I18N / TZ
# --------------------------------------------------------------------------- #

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"          # Always store UTC; localise at the presentation layer.
USE_I18N = True
USE_TZ = True


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "redact_secrets": {"()": "common.logging.RedactSecretsFilter"},
    },
    "formatters": {
        "structured": {
            "()": "common.logging.StructuredFormatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
            "filters": ["redact_secrets"],
        },
    },
    "root": {"handlers": ["console"], "level": env("DJANGO_LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"level": "WARNING", "propagate": True},
        "lumaindex": {"level": env("DJANGO_LOG_LEVEL", "INFO"), "propagate": True},
    },
}
