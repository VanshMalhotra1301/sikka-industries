import os
from datetime import timedelta
from dotenv import load_dotenv

# Load .env file in local development
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _fix_db_url(url: str) -> str:
    """
    1. Supabase/Heroku return 'postgres://' but SQLAlchemy 1.4+ requires 'postgresql://'.
    2. On Vercel, we switch to pg8000 (pure Python driver) to avoid binary compilation issues.
       pg8000 uses 'postgresql+pg8000://' scheme.
    """
    if not url:
        return url
    # Step 1: fix postgres:// → postgresql://
    if url.startswith('postgres://'):
        url = url.replace('postgres://', 'postgresql://', 1)
    # Step 2: inject pg8000 driver if no driver specified
    if url.startswith('postgresql://') and '+' not in url[:20]:
        url = url.replace('postgresql://', 'postgresql+pg8000://', 1)
    return url


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'sikka_super_secret_key_change_in_prod_2026')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)


class DevelopmentConfig(Config):
    """Local development — SQLite fallback if no DATABASE_URL set."""
    DEBUG = True
    _raw = os.environ.get('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'erp.db')}")
    SQLALCHEMY_DATABASE_URI = _fix_db_url(_raw) if 'sqlite' not in _raw else _raw
    # No pooling needed for SQLite / local dev
    SQLALCHEMY_ENGINE_OPTIONS = {}


class ProductionConfig(Config):
    """Production — Supabase PostgreSQL via pg8000 (pure Python, Vercel-safe)."""
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = _fix_db_url(os.environ.get('DATABASE_URL', ''))

    # NullPool is REQUIRED for serverless: each request gets a fresh connection.
    # Persistent pools don't work in stateless Vercel functions.
    from sqlalchemy.pool import NullPool
    SQLALCHEMY_ENGINE_OPTIONS = {
        'poolclass': NullPool,
    }

    @classmethod
    def init_app(cls, app):
        import logging
        logging.basicConfig(level=logging.INFO)


# Configuration map
config_map = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig,
}