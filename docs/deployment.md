# Deployment

Five containers on one Ubuntu host: Caddy, Nuxt, Django, PostgreSQL, and the
ingest worker. Nothing is published beyond `127.0.0.1`; `tailscale serve`
terminates TLS and is the only way in.

```text
      tailnet
         │  https://luma.your-tailnet.ts.net
         ▼
  tailscale serve       on the host — real cert, sets X-Forwarded-Proto
         │  http://127.0.0.1:8080
         ▼
      caddy             /api,/admin,/static → backend · everything else → frontend
       ├──► frontend    Nuxt, :3000
       └──► backend     Django + gunicorn, :8000
                 └──► postgres  :5432, never published
```

## First deployment

From a clone of this repo on your laptop:

```bash
cp deploy/deploy.env.example deploy/deploy.env && $EDITOR deploy/deploy.env
```

```bash
./deploy/deploy.sh bootstrap
```

`bootstrap` installs Docker, creates `/opt/lumaindex`, locks `ufw` down to SSH
plus the tailnet, enables unattended security upgrades, and points
`tailscale serve` at Caddy. It is idempotent.

Then the application config. Every `CHANGE_ME` must be replaced — the deploy
refuses to run while any remain.

```bash
cp .env.example .env && $EDITOR .env
```

```bash
python3 -c "import secrets; print('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64)); print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))"
```

```bash
docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(\"LUMA_FIELD_ENCRYPTION_KEY=\" + Fernet.generate_key().decode())'"
```

```bash
./deploy/deploy.sh env:push && ./deploy/deploy.sh && ./deploy/deploy.sh createsuperuser
```

### Onto a host that already does something else

`bootstrap.sh` assumes the machine is LumaIndex's: it rewrites ufw's rules, can
restart the Docker daemon — bouncing every container on the box — and points
`tailscale serve` at 443. On a shared server all three are destructive. Skip it
and do its three jobs by hand:

1. Install docker and the compose plugin; put the deploy user in `docker`.
2. `sudo mkdir -p /opt/lumaindex/{releases,shared,backups}` and `chown` it.
3. `sudo tailscale serve --bg --https=<free port> http://127.0.0.1:8080`.

Then `env:push` and `deploy` as normal. Nothing else in the deploy path touches
the host: Caddy binds `127.0.0.1:8080`, so no firewall rule is needed, and every
container, volume and network is prefixed `lumaindex`.

Any spare serve port works and its certificate is just as real — but set
`LUMA_PUBLIC_ORIGIN` and `DJANGO_CSRF_TRUSTED_ORIGINS` to include the port, or
logins fail CSRF with a message that never mentions ports.

## Everyday commands

| Command | What it does |
| --- | --- |
| `./deploy/deploy.sh` | Deploy the current working tree |
| `./deploy/deploy.sh status` | Release, container health, disk usage |
| `./deploy/deploy.sh logs backend` | Tail one service |
| `./deploy/deploy.sh rollback` | Switch back to the previous release |
| `./deploy/deploy.sh backup` | `pg_dump` plus the library mirror, onto this machine |
| `./deploy/deploy.sh verify` | `gzip -t` every dump, rehash every mirrored file |
| `./deploy/deploy.sh backup:status` | When the last backup ran; non-zero if stale |
| `./deploy/deploy.sh drill` | Full restore rehearsal against scratch copies |
| `./deploy/deploy.sh restore <file>` | Destructive DB restore, asks for confirmation |
| `./deploy/deploy.sh restore:library` | Send missing files back to the server |
| `./deploy/deploy.sh manage <cmd>` | Any Django management command |
| `./deploy/deploy.sh env:push` | Re-upload `.env` after editing it |

## How a deploy works

1. **Preflight** — SSH reachable, Docker usable, `.env` present with no
   placeholders, enough free disk.
2. **Sync** — the working tree is rsynced into
   `/opt/lumaindex/releases/<timestamp>-<sha>/`. (`DEPLOY_METHOD=git` has the
   server clone from the remote instead.)
3. **Build** — images built and tagged with the release stamp, which is recorded
   in `.image_tag` so `up -d` starts the code that was just built rather than
   whatever `:latest` points at.
4. **Switch** — `current` flips only after the build succeeds, so a broken build
   never touches what is running.
5. **Start** — `compose up -d --wait`. Migrations run in the backend entrypoint,
   before gunicorn accepts traffic.
6. **Health gate** — polls `/api/health/ready/` for up to ~3 minutes.
7. **Rollback on failure** — if it never turns healthy, `current` flips back and
   the backend logs are printed.

**Rollback reverts code, not the database.** Migrations that already ran stay
applied, so a release that both migrated and failed may leave the previous code
unable to run. For any migration that drops or renames a column, ship the
tolerant code first and the migration second — and back up before a risky one.

## Email

Password reset is the only mail this instance sends. Until it can send, reset
links only reach the backend log: fine for one person who can read the log,
not fine the moment a second person has an account.

```bash
LUMA_EMAIL_BACKEND=smtp
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=lumaindex@your-domain
```

Leave `EMAIL_USE_TLS` and `EMAIL_USE_SSL` blank and the port decides: 587
STARTTLS, 465 implicit TLS. Setting both is refused at startup rather than
quietly resolved.

```bash
./deploy/deploy.sh manage check_email you@example.com
```

It prints the configuration it will use — never the password — and turns the
usual first-time failures into a sentence saying what to change: wrong TLS mode
for the port, a From address the relay rejects, an account password where the
provider wanted an app password, credentials offered to a relay that wants none.

**You cannot test this through the app.** Password reset answers 204 whether or
not the address exists and whether or not the mail went out, because any other
answer lets someone enumerate users. So a broken relay is invisible from
outside: it is logged at ERROR as `auth.reset.send_failed`, and `check_email` is
how you look. `EMAIL_TIMEOUT` defaults to 10s because sending happens inside the
request and smtplib's own default wait is measured in minutes.

## Uploads and timeouts

Gunicorn runs the `gthread` worker, and that is not a performance preference.
With the sync worker `--timeout` caps a whole request including the body, so a
624 MB upload at 2 MB/s needs four minutes and dies at the 120s default —
appearing as a 500 after a two-minute wait, with a `SystemExit` in the log
rather than anything resembling "too slow". Caddy's access log is where it is
legible: `bytes_read` short of `Content-Length`, duration exactly
`GUNICORN_TIMEOUT`. For every other worker class that timeout is a liveness
heartbeat, which the thread worker keeps sending while a request streams.

`GUNICORN_WORKERS` × `GUNICORN_THREADS` is both the concurrency and the
PostgreSQL connection count. Keep the product under `max_connections` (100).

**When uploads are slow, look at the network first.** The first large upload on
the deployed instance failed twice: once on the sync worker above, and once
because Tailscale had not established a direct connection and was relaying
through a DERP server, which is shared and rate-limited. `tailscale status`
names it — `relay "sin"` rather than `direct` — and `tailscale netcheck` says
why. Here `MappingVariesByDestIP: true` meant symmetric NAT and `PortMapping:`
was empty at both ends, so nothing could open a port automatically and the
router was not forwarding UDP 41641; allowing that port through the host
firewall is necessary but not sufficient. A relayed path still works, at around
2 MB/s — which is why uploads are chunked and resumable rather than trusting one
connection to survive.

## Putting it on a phone

There is no install prompt on iOS. Open the instance in **Safari** (Chrome on
iOS cannot add to the Home Screen), then Share → Add to Home Screen. It runs
without browser chrome because the manifest declares `display: standalone`.

- **The phone has to be on the tailnet.** The MagicDNS name resolves nowhere
  else, so launching with Tailscale off gives a network error, not a cached
  library.
- **Nothing works offline.** There is no service worker.
- **iOS caches the manifest aggressively.** After changing it, delete the Home
  Screen icon and add it again, or the old settings persist.

## Backups

```bash
./deploy/deploy.sh backup
```

Both halves land **on the machine you ran it from**, which is the point: a
backup living on the host it backs up survives every failure except the one you
are afraid of.

```text
backups/
├── db/lumaindex-<stamp>.sql.gz   one snapshot per run
├── library/ab/cd/<sha256>.pdf    a mirror of the PDFs
└── manifest.txt                  what the last run saw
```

**The database** is small and changes constantly, so it is snapshotted: one
gzipped plain-SQL dump per run, `--clean --if-exists`. Plain SQL rather than
custom-format on purpose — it still restores after a PostgreSQL major-version
change, which is exactly when you need it. A copy stays on the server too, since
restoring from that one is a single command and no transfer. `BACKUP_KEEP`
(default 14) decides how many local dumps are kept.

**The library** is large and never changes: every file is named after the
SHA-256 of its own contents, so a file already in the mirror cannot have
different contents on the server. Only new files travel, which makes every
backup after the first cheap. The mirror is **additive** — a file no longer on
the server is either a book somebody deleted or a book somebody lost, and
nothing here can tell those apart, so it stays. `--prune-library` is how you say
you meant it.

The PDFs are the half that matters most: they are canonical, so a database dump
on its own restores a catalogue of books nobody can open. That is what
`--db-only` warns about. Thumbnails need no backup (`manage rebuild_thumbnails`
re-renders them) and staging holds only in-flight uploads.

Neither half contains `.env`. Without `LUMA_FIELD_ENCRYPTION_KEY` the dump
restores but its encrypted fields do not, so keep that in a password manager —
not on the same disk.

### Checking a backup is real

```bash
./deploy/deploy.sh verify
```

Every dump is tested with `gzip -t`, and every mirrored file is hashed against
its own name. That total check is free because the expected hash *is* the
filename — there is no separate checksum list to drift out of date. A backup
nobody has checked is a hypothesis.

### On a schedule

`deploy.sh` runs from your machine over SSH, so schedule it there. On a Mac use
launchd rather than cron: a laptop sleeps, and cron misses a 03:30 job on a
closed lid where launchd runs it on the next wake.

```bash
sed -e "s|__REPO__|$PWD|g" -e "s|__HOME__|$HOME|g" deploy/backup.launchd.plist \
  > ~/Library/LaunchAgents/local.lumaindex.backup.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.lumaindex.backup.plist
```

Daily at 03:30, logging to `~/Library/Logs/lumaindex-backup.log`. Remove it with
`launchctl bootout gui/$(id -u)/local.lumaindex.backup`.

The job needs an SSH key usable without a prompt — passphraseless or in the
keychain (`ssh-add --apple-use-keychain ~/.ssh/id_ed25519`). If
`env -u SSH_AUTH_SOCK ssh -o BatchMode=yes <host> true` works, so will the
schedule.

```bash
./deploy/deploy.sh backup:status
```

Reports when the last backup completed and how many files it holds, and exits
non-zero once that is older than `BACKUP_STALE_DAYS` (2). A job that quietly
stopped looks exactly like one that never ran, and the manifest is the only
thing that can tell them apart.

Set `BACKUP_DIR` in `deploy/deploy.env` to somewhere itself backed up or synced.
Two copies in one building is one copy.

### The restore drill

```bash
./deploy/deploy.sh drill
```

A restore you have never performed is a hypothesis. This runs the whole sequence
against scratch copies and cleans up after itself: the newest dump into a
scratch database, the library mirror into an empty directory, then the check
that matters — that every storage key the restored database references has bytes
on disk whose SHA-256 is its own name. Restoring the two halves separately
proves very little; what you need to know is whether the catalogue and the files
still agree afterwards. Nothing live is touched.

When you actually need it, restoring over the live database is
`./deploy/deploy.sh restore <file>`, which stops the app and asks for typed
confirmation. Putting the *files* back is separate:

```bash
./deploy/deploy.sh restore:library
```

It sends only what the server lacks and never overwrites — a file already there
has the contents its name says. After a restore onto an empty server, re-render
the thumbnails:

```bash
./deploy/deploy.sh manage rebuild_thumbnails
```

## Local development

```bash
cp .env.example .env
```

```bash
docker compose -f compose.yaml -f compose.dev.yaml up --build
```

http://localhost:8080 with hot reload on both sides. The dev override turns the
`Secure` cookie flags off (plain HTTP) and enables registration. Never use it on
a server.

```bash
docker compose run --rm --user root --entrypoint sh backend -c "pip install -q -r requirements-dev.txt && python -m pytest"
```

`--entrypoint` is required: the image's entrypoint ends with
`exec gunicorn "$@"`, so anything passed without it becomes a gunicorn argument
rather than a command.

```bash
./scripts/e2e.sh
```

The e2e run needs a real browser: PDF.js drives rendering with
`requestAnimationFrame`, which never fires where `visibilityState` is `hidden`,
so headless preview panes render nothing at all.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `400 Bad Request` on every page | The MagicDNS name is missing from `DJANGO_ALLOWED_HOSTS`. |
| Login returns 200 but you stay signed out | `Secure` cookies over plain HTTP. Finish the `tailscale serve` setup, or set both `*_COOKIE_SECURE` to `False`. |
| `CSRF verification failed` | `DJANGO_CSRF_TRUSTED_ORIGINS` does not exactly match the browser's origin, scheme and port included. |
| Cannot reach the docker daemon | The `docker` group was just added. Reconnect the SSH session once. |
| `tailscale serve` fails during bootstrap | HTTPS certificates are not enabled for the tailnet. Admin console → DNS → HTTPS Certificates. |
| Uploads fail with a 500 | A storage volume is not writable by the container. `entrypoint.sh` refuses to start and names the directory. |
| Uploads rejected with 507 | Two causes, told apart by the message. Either free disk is below `LUMA_MIN_FREE_DISK_BYTES` — storage is canonical and cannot evict, so free space or add a disk — or the account is over `LUMA_DEFAULT_USER_QUOTA_BYTES`, where trashed books still count and emptying the trash frees them. |
