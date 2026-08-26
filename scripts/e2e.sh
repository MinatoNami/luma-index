#!/usr/bin/env bash
#
# Run the reader's end-to-end tests against a scratch stack.
#
#   ./scripts/e2e.sh                 # all of them
#   ./scripts/e2e.sh reader.spec.ts  # one file
#
# It opens a book in a real browser, so it drives the `lumaindex-demo` project
# — seeded with public-domain books by scripts/demo_library.py — and never the
# default project, which is somebody's actual library. Pointing it somewhere
# else with COMPOSE_PROJECT is allowed; pointing it at an instance holding a
# book that is not the demo account's is refused.
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

# Defaults to the scratch project rather than to whatever `docker compose` would
# pick, because the safe thing has to be the thing that happens when you type
# the command with no arguments.
PROJECT="${COMPOSE_PROJECT:-lumaindex-demo}"
DEMO_EMAIL="reader@lumaindex.demo"
compose() { docker compose -p "$PROJECT" "$@"; }

step "Checking the $PROJECT stack is up"
compose ps --format '{{.Service}} {{.Status}}' | grep -q "caddy.*healthy" || die \
"No healthy caddy in project '$PROJECT'. Bring a scratch stack up and seed it:

  CADDY_HTTP_PORT=8091 docker compose -p lumaindex-demo \\
      -f compose.yaml -f compose.dev.yaml up -d
  docker compose -p lumaindex-demo exec -T backend \\
      python manage.py shell < scripts/demo_library.py
"

# The project name is a convention, not a guarantee: it says nothing about what
# is in the database it points at. This does. Deliberately no override — an
# escape hatch here would be used by accident exactly once.
step "Checking this is not a real library"
FOREIGN="$(compose exec -T backend python manage.py shell -c "
from library.models import Book
strangers = (Book.objects.exclude(owner__email='$DEMO_EMAIL')
             .values_list('owner__email', flat=True).distinct()[:5])
print('FOREIGN ' + (','.join(sorted(set(strangers))) or 'none'))
" 2>/dev/null | grep '^FOREIGN' | cut -d' ' -f2-)"

[ -n "$FOREIGN" ] || die "Could not check whose books these are. Refusing to run."
if [ "$FOREIGN" != "none" ]; then
    die "Project '$PROJECT' holds books owned by: $FOREIGN

This suite opens a book in a browser and is only ever pointed at demo data.
Seed a scratch instance with scripts/demo_library.py and run it against that."
fi

NETWORK="$(docker inspect "$(compose ps -q caddy)" \
  --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}')"
[ -n "$NETWORK" ] || die "Could not find the compose network."

step "Minting a session and finding a book"
FIXTURE="$(compose exec -T backend python manage.py shell -c '
from django.contrib.auth import get_user_model, SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from library.models import Book

# The demo account by name. "Any superuser" would happily sign in as a real
# person on an instance that also happened to hold demo books.
user = get_user_model().objects.filter(email="reader@lumaindex.demo").first()
if user is None:
    print("ERROR no demo account"); raise SystemExit(1)

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

# Warm the frontend before timing anything. Against the dev override Nuxt
# compiles a route on first request, which is slower than the first test's
# timeout and fails it — once, on a cold stack, in a way that looks like a
# rendering bug. The production image serves a build and skips this in a
# fraction of a second.
# The reader route specifically: Nuxt compiles per route, so warming only "/"
# leaves /books/<id> to compile inside the first test that opens it. With the
# session cookie, or this warms the login page instead.
step "Warming the frontend"
docker run --rm --network "$NETWORK" curlimages/curl:latest \
    -s -o /dev/null -m 180 -b "lumaindex_session=$SESSION" \
    "http://caddy:8080/books/$BOOK_ID" || true

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
