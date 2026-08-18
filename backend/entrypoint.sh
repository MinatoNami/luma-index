#!/usr/bin/env bash
# Backend container entrypoint: wait for Postgres, migrate, then serve.
set -euo pipefail

log() { printf '{"ts":"%s","level":"INFO","logger":"entrypoint","message":"%s"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1"; }

# --- Wait for PostgreSQL -----------------------------------------------------
# Compose's depends_on/healthcheck already gates this, but a database can also
# restart underneath a running container.
log "waiting for postgres at ${POSTGRES_HOST:-postgres}:${POSTGRES_PORT:-5432}"
attempt=0
until python -c "
import os, sys, psycopg
try:
    psycopg.connect(
        host=os.environ.get('POSTGRES_HOST', 'postgres'),
        port=os.environ.get('POSTGRES_PORT', '5432'),
        dbname=os.environ['POSTGRES_DB'],
        user=os.environ['POSTGRES_USER'],
        password=os.environ['POSTGRES_PASSWORD'],
        connect_timeout=3,
    ).close()
except Exception as exc:
    print(type(exc).__name__, file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; do
    attempt=$((attempt + 1))
    if [ "$attempt" -ge 60 ]; then
        log "postgres did not become reachable after 60 attempts; giving up"
        exit 1
    fi
    sleep 2
done
log "postgres is reachable"

# --- Schema ------------------------------------------------------------------
# Migrations run before the new code serves traffic. If this fails the container
# exits non-zero, compose reports it unhealthy, and deploy.sh rolls back rather
# than leaving a half-migrated database serving requests.
log "applying migrations"
python manage.py migrate --noinput

log "collecting static files"
python manage.py collectstatic --noinput --clear >/dev/null

# --- Optional first-run superuser -------------------------------------------
if [ -n "${DJANGO_SUPERUSER_EMAIL:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    log "ensuring bootstrap superuser exists"
    python manage.py shell <<'PYEOF'
import os
from django.contrib.auth import get_user_model

User = get_user_model()
email = os.environ["DJANGO_SUPERUSER_EMAIL"].lower()
if User.objects.filter(email=email).exists():
    print("bootstrap superuser already present; leaving it untouched")
else:
    User.objects.create_superuser(email=email,
                                  password=os.environ["DJANGO_SUPERUSER_PASSWORD"])
    print("bootstrap superuser created")
PYEOF
fi

log "starting gunicorn with ${GUNICORN_WORKERS:-3} workers"
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "${GUNICORN_WORKERS:-3}" \
    --timeout "${GUNICORN_TIMEOUT:-120}" \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile - \
    --access-logformat '{"ts":"%(t)s","level":"INFO","logger":"gunicorn.access","message":"%(r)s","status":%(s)s,"bytes":%(b)s,"duration_ms":%(M)s}' \
    "$@"
