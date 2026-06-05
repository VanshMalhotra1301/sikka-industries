import os
from datetime import timedelta
from dotenv import load_dotenv

# Load .env file in local development
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


def _fix_db_url(url: str) -> str:
    """Supabase / Heroku return 'postgres://' but SQLAlchemy 1.4+ requires 'postgresql://'."""
    if url and url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url


class Config:
    """Base configuration class."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'sikka_super_secret_key_change_in_prod_2026')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,      # Drop stale connections automatically
        'pool_recycle': 300,        # Recycle connections every 5 minutes
        'connect_args': {
            'connect_timeout': 10,
            'sslmode': 'require',   # Supabase requires SSL
        }
    }


class DevelopmentConfig(Config):
    """Development environment – falls back to local SQLite if no DATABASE_URL is set."""
    DEBUG = True
    _db_url = os.environ.get('DATABASE_URL', f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'erp.db')}")
    SQLALCHEMY_DATABASE_URI = _fix_db_url(_db_url)
    # SQLite doesn't support SSL or many pool options
    if 'sqlite' in _db_url:
        SQLALCHEMY_ENGINE_OPTIONS = {}


class ProductionConfig(Config):
    """Production environment – Supabase / any external PostgreSQL."""
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = _fix_db_url(os.environ.get('DATABASE_URL', ''))

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