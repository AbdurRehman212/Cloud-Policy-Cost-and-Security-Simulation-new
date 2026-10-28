import os
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv

load_dotenv(override=True)

# Credential-free local default; set DATABASE_URL in backend/.env (git-ignored) with real credentials.
PG_URL = 'postgresql://localhost/cloud_simulator'


def _normalize_base_url(url, fallback):
    """Return a safe absolute base URL without a trailing slash."""
    candidate = (url or fallback or '').strip()
    if not candidate:
        return ''

    if '://' not in candidate:
        candidate = f'https://{candidate}'

    parsed = urlsplit(candidate)
    path = (parsed.path or '').rstrip('/')
    normalized = parsed._replace(path=path, query='', fragment='')
    return urlunsplit(normalized)

class Config:
    """Base configuration class."""
    # App Settings
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    # Database — PostgreSQL only; SQLite is NOT supported
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or PG_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 5,
        'pool_recycle': 60,
    }
    # JWT Settings
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'jwt-secret-change-in-production'
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)
    # Redis
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    # Email
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER')
    FRONTEND_BASE_URL = _normalize_base_url(
        os.environ.get('FRONTEND_BASE_URL') or os.environ.get('PUBLIC_APP_URL'),
        '',
    )
    # AI/ML Settings
    MODEL_PATH = os.environ.get('MODEL_PATH') or './ai_training/models'
    DATASET_PATH = os.environ.get('DATASET_PATH') or './data'
    FINOPS_DATASET_PATH = os.environ.get('FINOPS_DATASET_PATH') or os.path.join(DATASET_PATH, 'finops')
    SECURITY_DATASET_PATH = os.environ.get('SECURITY_DATASET_PATH') or os.path.join(DATASET_PATH, 'cicids_subset.csv')
    GOVERNANCE_DATASET_PATH = os.environ.get('GOVERNANCE_DATASET_PATH') or os.path.join(DATASET_PATH, 'governance')
    SIMULATOR_CORE_DATASET_PATH = os.environ.get('SIMULATOR_CORE_DATASET_PATH') or os.path.join(DATASET_PATH, 'simulator_core')
    # Simulation Settings
    SIMULATION_TICK_INTERVAL = int(os.environ.get('SIMULATION_TICK_INTERVAL', 5))
    MAX_SIMULATED_RESOURCES = int(os.environ.get('MAX_SIMULATED_RESOURCES', 100))
    DEFAULT_CURRENCY = os.environ.get('DEFAULT_CURRENCY', 'USD')
    ENABLE_SIMULATION_THREADS = os.environ.get('ENABLE_SIMULATION_THREADS', 'true').lower() == 'true'
    # Destructive, system-wide reset endpoint. Off unless explicitly enabled for local development;
    # scripts/reset_system.py is the supported way to reset a development database.
    ALLOW_SYSTEM_RESET = os.environ.get('ALLOW_SYSTEM_RESET', 'false').lower() == 'true'
    ENABLE_REALTIME_METRICS = os.environ.get('ENABLE_REALTIME_METRICS', 'true').lower() == 'true'
    # Pricing (Simulated AWS-like pricing per hour)
    VM_PRICING = {
        't2.micro': 0.0116,
        't2.small': 0.023,
        't2.medium': 0.0464,
        't2.large': 0.0928,
        'm5.large': 0.096,
        'm5.xlarge': 0.192,
        'c5.large': 0.085,
        'c5.xlarge': 0.17
    }
    DB_PRICING = {
        'db.t2.micro': 0.017,
        'db.t2.small': 0.034,
        'db.m5.large': 0.192,
        'db.r5.large': 0.24
    }
class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('DEV_DATABASE_URL') or os.environ.get('DATABASE_URL') or PG_URL
class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or PG_URL
class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL') or 'sqlite://'
    SQLALCHEMY_ENGINE_OPTIONS = {}
    ENABLE_SIMULATION_THREADS = False
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
