# Settings overrides for the Docker image (see ../Dockerfile,
# ../docker-compose.yml). Values are pulled from environment variables so
# the container is configurable without rebuilding it.

import os


def _bool_env(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


DEBUG = _bool_env("AMAGAMA_DEBUG")
SECRET_KEY = os.environ.get("AMAGAMA_SECRET_KEY", "please-change-me")
ENABLE_WEB_UI = _bool_env("AMAGAMA_ENABLE_WEB_UI", default=True)
ENABLE_DATA_ALTERING_API = _bool_env("AMAGAMA_ENABLE_DATA_ALTERING_API")

DB_NAME = os.environ.get("DB_NAME", "amagama")
DB_USER = os.environ.get("DB_USER", "amagama")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_HOST = os.environ.get("DB_HOST", "postgres")
DB_PORT = os.environ.get("DB_PORT", "5432")

CACHE_TYPE = os.environ.get("CACHE_TYPE", "SimpleCache")
