#!/bin/sh
# Single-container entry. Order matters:
#   1. Apply Alembic migrations (idempotent; seeds admin user).
#   2. Start uvicorn on :8000 in the background.
#   3. Start nginx on :$PORT in the foreground (PID 1, gets signals).
#
# Fly's machine restart policy expects one foreground process. nginx
# being PID 1 means a crash there triggers an automatic restart.

set -eu

# Postgres DSN: Fly attaches DATABASE_URL when you `fly postgres attach`.
# Expand into the individual POSTGRES_* env our config.py reads.
if [ -n "${DATABASE_URL:-}" ]; then
    export POSTGRES_DSN="$DATABASE_URL"
fi

cd /app/backend

# 1. Migrations -- alembic 0001..0003. Safe to re-run on every start.
echo "[start] alembic upgrade head"
alembic upgrade head || {
    echo "[start] alembic failed; continuing so the panel still boots"
}

# 2. uvicorn in the background. WHY no --reload: this is production-ish.
echo "[start] uvicorn on :8000"
uvicorn waf_panel.main:app --host 127.0.0.1 --port 8000 &

# 3. nginx in the foreground. -g 'daemon off;' keeps it as PID 1 so
#    Fly's process supervisor can detect a crash.
echo "[start] nginx on :${PORT:-8080}"
exec nginx -g 'daemon off;'
