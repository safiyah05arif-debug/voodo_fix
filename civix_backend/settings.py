"""
CIVIX (FixMyCity) — Django Settings
====================================
Configures Django with MongoEngine (PyMongo) for MongoDB Atlas,
Django REST Framework, and CORS headers.

MongoDB Atlas is the PRIMARY database for all domain models (issues, users,
badges, etc.) via MongoEngine ODM.  SQLite is kept as a minimal Django
default backend for admin/sessions/auth scaffolding only.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ── Load environment variables from .env ──────────────────────────────────────
load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent

# ── Security ──────────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-key-change-me",
)
DEBUG = os.getenv("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")
ALLOWED_HOSTS = os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# ── Installed Applications ────────────────────────────────────────────────────
INSTALLED_APPS = [
    # Django core
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "corsheaders",
    # CIVIX apps
    "issues",
    "users",
]

# ── Middleware ─────────────────────────────────────────────────────────────────
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",        # Must be first
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "users.middleware.RoleAccessMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ── URL Configuration ─────────────────────────────────────────────────────────
ROOT_URLCONF = "civix_backend.urls"

# ── Templates ──────────────────────────────────────────────────────────────────
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "civix_backend.wsgi.application"


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
# Django's built-in ORM uses SQLite for admin/sessions scaffolding only.
# All CIVIX domain data lives in MongoDB Atlas via MongoEngine.
# =============================================================================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# =============================================================================
# MONGODB ATLAS CONNECTION (MongoEngine)
# =============================================================================
# The connection is established once at Django startup via mongoengine.connect().
# All domain models in `issues/models.py` and `users/models.py` use this.
# =============================================================================
import mongoengine  # noqa: E402

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_NAME = os.getenv("MONGODB_NAME", "civix_db")

if MONGODB_URI:
    # Production / Atlas connection
    mongoengine.connect(
        db=MONGODB_NAME,
        host=MONGODB_URI,
        alias="default",
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )
    print(f"[CIVIX] Connected to MongoDB Atlas -- database: {MONGODB_NAME}")
else:
    # Fallback: local MongoDB instance for development without Atlas
    mongoengine.connect(
        db=MONGODB_NAME,
        host="localhost",
        port=27017,
        alias="default",
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
    )
    print(f"[CIVIX] WARNING: No MONGODB_URI found -- using local MongoDB: {MONGODB_NAME}")


# ── Password Validation ───────────────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ── Internationalization ──────────────────────────────────────────────────────
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"  # IST for Indian civic platform
USE_I18N = True
USE_TZ = True

# ── Static Files ──────────────────────────────────────────────────────────────
STATIC_URL = "static/"

# ── Default Primary Key ──────────────────────────────────────────────────────
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# =============================================================================
# DJANGO REST FRAMEWORK
# =============================================================================
REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%S%z",
}

# ── CORS (allow frontend dev server) ─────────────────────────────────────────
CORS_ALLOW_ALL_ORIGINS = DEBUG  # Only in development
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]


# =============================================================================
# CIVIX CUSTOM SETTINGS
# =============================================================================

# ── Supabase Storage ──────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "")
SUPABASE_BUCKET_NAME = os.getenv("SUPABASE_BUCKET_NAME", "civix-uploads")

# ── AI Vision Provider ────────────────────────────────────────────────────────
AI_PROVIDER = os.getenv("AI_PROVIDER", "openai")  # "openai" or "gemini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── SLA Deadlines (hours) per severity level ──────────────────────────────────
SLA_DEADLINES = {
    "critical": 24,
    "high": 48,
    "medium": 72,
    "low": 168,   # 7 days
}

# ── Priority Score Weights ────────────────────────────────────────────────────
# Formula: Score = (Severity * 40) + (Upvotes * 20) + (Hours_Pending * 10) + (LocationRisk * 30)
PRIORITY_WEIGHTS = {
    "severity": 40,
    "upvotes": 20,
    "hours_pending": 10,
    "location_risk": 30,
}

# ── Spatial Deduplication Radius (meters) ─────────────────────────────────────
DEDUP_RADIUS_METERS = 50
