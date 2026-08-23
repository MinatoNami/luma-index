#!/usr/bin/env bash
#
# Regenerates the README screenshots from a scratch instance.
#
# Never point this at a real library: the shots go into a public repository,
# and a screenshot of somebody's actual shelf publishes what they read. Seed a
# separate compose project with scripts/demo_library.py and shoot that.
#
#   CADDY_HTTP_PORT=8091 docker compose -p lumaindex-demo \
#       -f compose.yaml -f compose.dev.yaml up -d
#   docker compose -p lumaindex-demo exec -T backend \
#       python manage.py shell < scripts/demo_library.py
#   ./scripts/screenshots.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

PROJECT="${COMPOSE_PROJECT:-lumaindex-demo}"
OUT_DIR="docs/screenshots"

step() { printf '\033[34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m ✗ \033[0m %s\n' "$*" >&2; exit 1; }

compose() { docker compose -p "$PROJECT" "$@"; }

step "Checking the scratch stack is up"
compose ps --format '{{.Service}} {{.Status}}' | grep -q "caddy.*healthy" \
  || die "No healthy caddy in project '$PROJECT'. See the header of this script."

NETWORK="$(docker inspect "$(compose ps -q caddy)" \
  --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}')"
[ -n "$NETWORK" ] || die "Could not find the compose network."

step "Minting a session"
FIXTURE="$(compose exec -T backend python manage.py shell -c '
from django.contrib.auth import (BACKEND_SESSION_KEY, HASH_SESSION_KEY,
                                 SESSION_KEY, get_user_model)
from django.contrib.sessions.backends.db import SessionStore
from library.models import Book

user = get_user_model().objects.order_by("pk").first()
book = (Book.objects.filter(deleted_at__isnull=True, page_count__gt=3)
        .order_by("-page_count").first())
if user is None or book is None:
    print("ERROR seed the instance first"); raise SystemExit(1)

s = SessionStore()
s[SESSION_KEY] = str(user.pk)
s[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
s[HASH_SESSION_KEY] = user.get_session_auth_hash()
s.set_expiry(1800)
s.create()
print(f"FIXTURE {s.session_key} {book.pk}")
' 2>/dev/null | grep '^FIXTURE' || true)"

case "$FIXTURE" in FIXTURE*) : ;; *) die "Could not mint a session." ;; esac
SESSION="$(echo "$FIXTURE" | awk '{print $2}')"
BOOK_ID="$(echo "$FIXTURE" | awk '{print $3}')"

cleanup() {
  compose exec -T backend python manage.py shell -c "
from django.contrib.sessions.models import Session
Session.objects.filter(session_key='$SESSION').delete()" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Pinned to the installed @playwright/test: the browsers in the image have to
# match the client driving them.
VERSION="$(docker run --rm -v "$PWD/frontend":/w -w /w node:22-slim \
  node -e 'process.stdout.write(require("@playwright/test/package.json").version)')"

mkdir -p "$OUT_DIR"
step "Capturing with Playwright ${VERSION}"
docker run --rm \
  --network "$NETWORK" \
  -v "$PWD/scripts":/s \
  -v "$PWD/frontend/node_modules":/s/node_modules:ro \
  -v "$PWD/$OUT_DIR":/out \
  -e BASE_URL=http://caddy:8080 \
  -e SESSION="$SESSION" \
  -e BOOK_ID="$BOOK_ID" \
  -w /s \
  "mcr.microsoft.com/playwright:v${VERSION}-noble" \
  node capture.mjs

step "Done"
ls -la "$OUT_DIR"
