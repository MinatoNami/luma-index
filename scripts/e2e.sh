#!/usr/bin/env bash
#
# Run the reader's end-to-end tests against the development stack.
#
#   ./scripts/e2e.sh                 # all of them
#   ./scripts/e2e.sh reader.spec.ts  # one file
#
# Playwright runs in its own container with the browsers already in the image,
# so nothing is downloaded onto this machine. It joins the compose network and
# talks to `caddy:8080`, a hostname Django already allows — the app does not
# have to be reconfigured to be testable.
#
# The session is minted server-side rather than typed into the login form:
# these are tests about the reader, and a password step would only give them a
# second reason to fail.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

step() { printf '\033[34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
die()  { printf '\033[31m ✗ \033[0m %s\n' "$*" >&2; exit 1; }

compose() { docker compose "$@"; }

step "Checking the stack is up"
compose ps --format '{{.Service}} {{.Status}}' | grep -q "caddy.*healthy" \
  || die "The dev stack is not running. Start it with: docker compose up -d"

NETWORK="$(docker inspect "$(compose ps -q caddy)" \
  --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}')"
[ -n "$NETWORK" ] || die "Could not find the compose network."

step "Minting a session and finding a book"
FIXTURE="$(compose exec -T backend python manage.py shell -c '
from django.contrib.auth import get_user_model, SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from library.models import Book

user = get_user_model().objects.filter(is_superuser=True).first() or get_user_model().objects.first()
if user is None:
    print("ERROR no accounts"); raise SystemExit(1)

# A book with pages to turn and, ideally, text to search.
book = (Book.objects.filter(deleted_at__isnull=True, has_text_layer=True, page_count__gt=3).first()
        or Book.objects.filter(deleted_at__isnull=True).first())
if book is None:
    print("ERROR no books"); raise SystemExit(1)

s = SessionStore()
s[SESSION_KEY] = str(user.pk)
s[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
s[HASH_SESSION_KEY] = user.get_session_auth_hash()
s.set_expiry(3600)
s.create()
print(f"FIXTURE {s.session_key} {book.pk}")
' 2>/dev/null | grep '^FIXTURE' || true)"

case "$FIXTURE" in
  FIXTURE*) : ;;
  *) die "Could not prepare a session and a book. Is there an account with at least one book?" ;;
esac
SESSION="$(echo "$FIXTURE" | awk '{print $2}')"
BOOK_ID="$(echo "$FIXTURE" | awk '{print $3}')"
printf '    session %s… book %s\n' "${SESSION:0:8}" "$BOOK_ID"

cleanup() {
  compose exec -T backend python manage.py shell -c "
from django.contrib.sessions.models import Session
Session.objects.filter(session_key='$SESSION').delete()" >/dev/null 2>&1 || true
}
trap cleanup EXIT

# Pinned to the installed @playwright/test, because the browsers in the image
# have to match the client driving them.
VERSION="$(docker run --rm -v "$PWD/frontend":/w -w /w node:22-slim \
  node -e 'process.stdout.write(require("@playwright/test/package.json").version)')"

step "Running Playwright ${VERSION}"
docker run --rm \
  --network "$NETWORK" \
  -v "$PWD/frontend":/w -w /w \
  -e LUMA_E2E_BASE_URL=http://caddy:8080 \
  -e LUMA_E2E_SESSION="$SESSION" \
  -e LUMA_E2E_BOOK_ID="$BOOK_ID" \
  -e CI="${CI:-}" \
  "mcr.microsoft.com/playwright:v${VERSION}-noble" \
  npx playwright test "$@"
