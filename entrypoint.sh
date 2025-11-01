#!/usr/bin/env bash
set -euo pipefail

# Optional: wait for Postgres to be ready
# Render-managed Postgres is ready on deploy, but for robustness we wait
PG_URL="${DATABASE_URL:-}"

wait_for_postgres() {
  python - <<PY
import os, time
from urllib.parse import urlparse
url = os.getenv("DATABASE_URL")
if not url:
    print("DATABASE_URL not set, skipping wait")
    raise SystemExit(0)
import psycopg2, psycopg2.extras
from time import sleep
for i in range(30):
    try:
        conn = psycopg2.connect(url)
        conn.close()
        print("Postgres reachable")
        break
    except Exception as e:
        print("Waiting for Postgres...", e)
        time.sleep(2)
else:
    print("Postgres not reachable after wait, continuing anyway")
PY
}

# Wait for DB (safe)
wait_for_postgres || true

# Run DB creation/migrations.
# We rely on backend.database to create tables async; make sure it supports being run as a module.
echo "Running DB table creation (backend.database)..."
python -m backend.database || echo "DB create script returned non-zero (may have run already)."

# Optional: run Alembic migrations instead if you have them configured:
# echo "Running alembic upgrade head"
# alembic upgrade head

# Start uvicorn
echo "Starting uvicorn..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 1
