# AMAGAMA_CONFIG override used by CI to point amagama-manage at the
# "postgres" service container (see .github/workflows/ci.yml). Not used by
# the test suite itself, which manages its own ephemeral PostgreSQL via
# pytest-postgresql.

DB_NAME = "amagama"
DB_USER = "postgres"
DB_PASSWORD = "postgres"
DB_HOST = "localhost"
DB_PORT = "5432"
