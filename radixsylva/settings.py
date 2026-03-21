"""
Django settings — Radix Sylva (base botanique publique).
PostgreSQL recommandé (SearchVector + Gin). SQLite possible pour tests rapides.
"""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, True),
    CORS_ALLOW_ALL_ORIGINS=(bool, True),
)
environ.Env.read_env(BASE_DIR / '.env')

SECRET_KEY = env(
    'SECRET_KEY',
    default='django-insecure-radixsylva-dev-only-change-in-production',
)
DEBUG = env('DEBUG')
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1', '0.0.0.0'])
if DEBUG and '0.0.0.0' not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append('0.0.0.0')

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'corsheaders',
    'drf_spectacular',
    'botanique.apps.BotaniqueConfig',
]

if env('DATABASE_URL', default=None):
    DATABASES = {'default': env.db()}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
    INSTALLED_APPS.insert(
        INSTALLED_APPS.index('django.contrib.staticfiles') + 1,
        'django.contrib.postgres',
    )

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'radixsylva.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
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

WSGI_APPLICATION = 'radixsylva.wsgi.application'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'fr-ca'
TIME_ZONE = 'America/Toronto'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOW_ALL_ORIGINS = env('CORS_ALLOW_ALL_ORIGINS')

REST_FRAMEWORK = {
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'Radix Sylva API',
    'DESCRIPTION': 'Base botanique publique — monde tempéré (focus Québec/Canada)',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# Sync bulk (Pass B) — clé optionnelle
RADIX_SYLVA_SYNC_API_KEYS = env.list('RADIX_SYLVA_SYNC_API_KEYS', default=[])
