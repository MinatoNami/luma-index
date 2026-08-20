# Deployment

LumaIndex runs as four containers on one Ubuntu host: Caddy, Nuxt, Django, and
PostgreSQL. Nothing is published beyond `127.0.0.1`; `tailscale serve`
terminates TLS and is the only way in.

```
      tailnet
         │  https://luma.your-tailnet.ts.net
         ▼
  tailscale serve            (on the host — real cert, sets X-Forwarded-Proto)
         │  http://127.0.0.1:8080
         ▼
      caddy                  /api,/admin,/static → backend   ·   everything else → frontend
       ├──────────────► frontend  (Nuxt, :3000)
       └──────────────► backend   (Django + gunicorn, :8000)
                              │
                              ▼
                          postgres  (:5432, never published)
```

## Deploying onto a host that already does something else

`bootstrap.sh` assumes the machine is LumaIndex's. It rewrites ufw's rules, can
restart the Docker daemon — bouncing every container on the box — and points
`tailscale serve` at 443. On a shared server all three are destructive, so skip
it and do its three jobs by hand:

1. Install docker and the compose plugin, and put the deploy user in the
   `docker` group.
2. `sudo mkdir -p /opt/lumaindex/{releases,shared,backups}` and `chown` it to
   that user.
3. `sudo tailscale serve --bg --https=<free port> http://127.0.0.1:8080`.

Then `env:push` and `deploy` as normal. Nothing else in the deploy path touches
the host: Caddy binds `127.0.0.1:8080`, so no firewall rule is needed, and
every container, volume and network is prefixed `lumaindex`.

Pick the serve port to suit the host. 443 is the default because it is the
tidiest URL; if something already holds it, any spare port works and the
certificate is just as real — set `LUMA_PUBLIC_ORIGIN` and
`DJANGO_CSRF_TRUSTED_ORIGINS` to include it, or logins fail CSRF with a message
that does not mention ports.

## First deployment

On your laptop, from a clone of this repo:

```bash
cp deploy/deploy.env.example deploy/deploy.env && $EDITOR deploy/deploy.env
```

```bash
./deploy/deploy.sh bootstrap
```

`bootstrap` installs Docker, creates `/opt/lumaindex`, locks `ufw` down to SSH
plus the tailnet, enables unattended security upgrades, and points
`tailscale serve` at Caddy. It is idempotent — re-run it any time.

Then the application config:

```bash
cp .env.example .env && $EDITOR .env
```

Every `CHANGE_ME` must be replaced; the deploy refuses to run while any remain.
Generate the secrets with:

```bash
python3 -c "import secrets; print('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64)); print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(32))"
```

```bash
docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(\"LUMA_FIELD_ENCRYPTION_KEY=\" + Fernet.generate_key().decode())'"
```

Upload it and deploy:

```bash
./deploy/deploy.sh env:push
```

```bash
./deploy/deploy.sh
```

Create your account:

```bash
./deploy/deploy.sh createsuperuser
```

## Everyday commands

| Command | What it does |
| --- | --- |
| `./deploy/deploy.sh` | Deploy the current working tree |
| `./deploy/deploy.sh status` | Release, container health, disk usage |
| `./deploy/deploy.sh logs backend` | Tail one service |
| `./deploy/deploy.sh rollback` | Switch back to the previous release |
| `./deploy/deploy.sh backup --download` | `pg_dump`, keep a copy locally |
| `./deploy/deploy.sh restore <file>` | Destructive restore, asks for confirmation |
| `./deploy/deploy.sh manage <cmd>` | Any Django management command |
| `./deploy/deploy.sh env:push` | Re-upload `.env` after editing it |

## How a deploy works

1. **Preflight** — SSH reachable, Docker usable by the deploy user, `.env`
   present with no placeholders, enough free disk.
2. **Sync** — the working tree is rsynced into
   `/opt/lumaindex/releases/<timestamp>-<sha>/`. (Set `DEPLOY_METHOD=git` to
   have the server clone from the remote instead.)
3. **Build** — images are built and tagged with the release stamp.
4. **Switch** — the `current` symlink flips only after the build succeeds, so a
   broken build never touches what is running.
5. **Start** — `compose up -d --wait`. Migrations run inside the backend
   entrypoint, before gunicorn accepts traffic.
6. **Health gate** — the deploy polls `/api/health/ready/` for up to ~3 minutes.
7. **Rollback on failure** — if it never turns healthy, `current` flips back to
   the previous release and the backend logs are printed.

### What rollback does not do

**Rollback reverts code, not the database.** Migrations that already ran stay
applied. If a release both migrated the schema and failed, the previous code
may not run against the new schema, and the rollback will not save you.

For any migration that drops or renames a column, deploy it in two steps: ship
the code that tolerates both shapes first, then the migration. And take a
backup before a risky migration:

```bash
./deploy/deploy.sh backup --download
```

## Email

Password reset is the only mail this instance sends, and until it can send,
reset links only ever reach the backend log. That is fine for one person who
can read the log and nobody else; it stops being fine the moment a second
person has an account.

Set the relay in `.env`:

```bash
LUMA_EMAIL_BACKEND=smtp
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_HOST_USER=...
EMAIL_HOST_PASSWORD=...
DEFAULT_FROM_EMAIL=lumaindex@your-domain
```

Leave `EMAIL_USE_TLS` and `EMAIL_USE_SSL` blank and the port decides: 587 uses
STARTTLS, 465 uses implicit TLS. Setting both is refused at startup rather than
quietly resolved, because the two are contradictory and picking one for you
would hide the mistake until somebody needed a password reset.

Then check it, which is a separate step on purpose:

```bash
./deploy/deploy.sh manage check_email you@example.com
```

It prints the configuration it is about to use — never the password — and turns
the usual first-time failures into a sentence saying what to change: the wrong
TLS mode for the port, a From address the relay will not accept, an account
password where the provider wanted an app password, credentials offered to a
relay that does not want them.

**Why you cannot test this by using the app.** Password reset answers 204
whether or not the address has an account, and whether or not the mail went
out. That is deliberate: any other answer turns the endpoint into a way to
enumerate users, and a 500 from a refused SMTP handshake would appear only for
addresses that exist. The cost is that a broken relay is invisible from
outside, so it is logged at ERROR — `event: auth.reset.send_failed` — and
`check_email` is how you look.

`EMAIL_TIMEOUT` defaults to 10 seconds. Sending happens inside the request, and
smtplib's own default wait is measured in minutes, so an unreachable relay
would otherwise hold a gunicorn worker open on every attempt until there were
none left.

## Uploads that take longer than the timeout

Gunicorn runs the `gthread` worker, and that is not a performance preference.

With the sync worker `--timeout` is the ceiling on a whole request, and the
request body counts towards it. A 624 MB upload over a link doing 2 MB/s needs
about four minutes, so at the 120-second default the worker was killed
mid-stream: the reader waited two minutes and got a 500, and the log showed a
`SystemExit` inside gunicorn's abort handler rather than anything resembling
"too slow". Caddy's access log is where it is legible — `bytes_read` well short
of `Content-Length`, and a duration exactly equal to `GUNICORN_TIMEOUT`.

For every other worker class gunicorn treats `--timeout` as a liveness
heartbeat, which the thread worker keeps sending while a request is still
streaming. Long uploads and long PDF downloads then cost a thread rather than a
whole process.

`GUNICORN_WORKERS` x `GUNICORN_THREADS` is both the concurrency and the
PostgreSQL connection count. Keep the product under `max_connections`, which is
100 by default.

## When uploads are slow, look at the network before the app

The first large upload on the deployed instance failed twice, and neither cause
was in the application.

The first was gunicorn's sync worker, above. The second was the path: Tailscale
had not established a direct connection and was relaying everything through a
DERP server, which is shared and rate-limited. `tailscale status` names it —
`relay "sin"` rather than `direct` — and `tailscale netcheck` says why.

On this host `MappingVariesByDestIP: true` on the client meant symmetric NAT,
`PortMapping:` was empty on both ends, so nothing could open a port
automatically, and the server's router was not forwarding UDP 41641. Allowing
that port through the host's own firewall is necessary but not sufficient; the
router in front of it has to forward too.

A relayed path still works. It is simply slow enough — around 2 MB/s here —
that a large upload becomes a multi-minute request, which is why uploads are
chunked and resumable rather than relying on one connection surviving.

## Putting it on a phone

There is no install prompt on iOS — you have to go and find it. Open the
instance in **Safari** (Chrome on iOS cannot add to the Home Screen), then
Share → Add to Home Screen. It then runs without browser chrome, because the
manifest declares `display: standalone`.

Two things to expect:

* **The phone has to be on the tailnet.** The MagicDNS name does not resolve
  anywhere else, so launching the app with Tailscale off gives a network error,
  not a cached library.
* **Nothing works offline.** There is no service worker. That is deliberate: a
  stale cache in front of a PDF library is a worse failure than a clear network
  error, and none of this is useful without the server anyway.

iOS caches the manifest and its metas aggressively. After changing either,
delete the Home Screen icon and add it again, or the old settings persist.

## Backups

```bash
./deploy/deploy.sh backup
```

One command takes both halves, and both land **on the machine you ran it
from** — which is the point. A backup living on the host it backs up survives
every failure except the one you are actually afraid of.

```text
backups/
├── db/lumaindex-<stamp>.sql.gz   one snapshot per run
├── library/ab/cd/<sha256>.pdf    a mirror of the PDFs
└── manifest.txt                  what the last run saw
```

The two halves fail differently, so they are treated differently.

**The database** is small and changes constantly, so it is snapshotted: one
gzipped plain-SQL dump per run, `--clean --if-exists`. Plain SQL rather than a
custom-format dump on purpose — it still restores after a PostgreSQL
major-version change, which is exactly when you need it most. A copy also stays
on the server, because restoring from that one is a single command and no
transfer. `BACKUP_KEEP` (default 14) decides how many local dumps are kept.

**The library** is large and never changes. Every file is named after the
SHA-256 of its own contents, so a file already in the mirror cannot have
different contents on the server — there is nothing to snapshot. Only new files
travel, which makes the second backup and every one after it cheap.

The mirror is **additive**. A file in it that is no longer on the server is
either a book somebody deleted or a book somebody lost, and nothing here can
tell those apart, so it stays. `--prune-library` is how you say you meant it.

The PDFs are the half that matters most. They are canonical — LumaIndex is the
only place they exist, unless the uploader still has the original — so a
database dump on its own restores a catalogue of books nobody can open. That is
what `--db-only` warns about, and it is a change from the Drive-backed design
where the local copy was a cache and PRD §38 correctly said not to back it up.
Owning the storage inverts that.

Thumbnails and staging need no backup: thumbnails re-render from the PDFs
(`./deploy/deploy.sh manage rebuild_thumbnails`), and staging holds only
in-flight uploads.

Neither half contains `.env`. Without `LUMA_FIELD_ENCRYPTION_KEY` the dump
restores but its encrypted fields do not, so keep that somewhere else — a
password manager, not the same disk.

### Checking a backup is real

```bash
./deploy/deploy.sh verify
```

Every dump is tested with `gzip -t`, and every file in the mirror is hashed and
compared against its own name. That total check is free because of how storage
is addressed: the expected hash is the filename, so there is no separate
checksum list that can drift out of date with the thing it describes.

Run it after the first backup, and on a schedule if you have one. A backup
nobody has checked is a hypothesis.

### Doing this on a schedule

`deploy.sh` runs from your machine over SSH, so schedule it there.

On a Mac use launchd rather than cron: a laptop sleeps, and cron simply misses
a 03:30 job on a closed lid while launchd runs it on the next wake. There is a
ready-made agent in the repo:

```bash
sed -e "s|__REPO__|$PWD|g" -e "s|__HOME__|$HOME|g" deploy/backup.launchd.plist \
  > ~/Library/LaunchAgents/local.lumaindex.backup.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.lumaindex.backup.plist
```

It logs to `~/Library/Logs/lumaindex-backup.log`. Remove it with
`launchctl bootout gui/$(id -u)/local.lumaindex.backup`.

The job needs an SSH key it can use without a prompt — either passphraseless or
in the keychain (`ssh-add --apple-use-keychain ~/.ssh/id_ed25519`). Check with
`env -u SSH_AUTH_SOCK ssh -o BatchMode=yes <host> true`: if that works, so will
the schedule.

### Knowing the schedule is still running

```bash
./deploy/deploy.sh backup:status
```

Reports when the last backup completed and how many files it holds, and exits
non-zero once that is older than `BACKUP_STALE_DAYS` (2). A job that quietly
stopped running looks exactly like one that never ran, and the manifest is the
only thing that can tell them apart.

Set `BACKUP_DIR` in `deploy/deploy.env` to put the backup somewhere that is
itself backed up or synced — an external disk, a NAS mount, a synced folder.
Two copies in one building is one copy.

### The restore drill

A restore you have never performed is a hypothesis. Rehearse it against a
scratch database rather than the live one, so a mistake during the rehearsal
costs nothing.

Take the dump:

```bash
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' | gzip -c > drill.sql.gz
```

Restore it beside the real database:

```bash
docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists restore_drill && createdb -U "$POSTGRES_USER" restore_drill'
```

```bash
gunzip -c drill.sql.gz | docker compose exec -T postgres sh -c 'psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d restore_drill'
```

Compare the row counts against the live database — users, folders, books,
sources, highlights, reading progress:

```bash
docker compose exec -T postgres sh -c 'psql -t -A -U "$POSTGRES_USER" -d restore_drill -c "SELECT count(*) FROM library_book;"'
```

Then check that the storage keys in the restored rows correspond to files in
the `library` volume. That is the step that catches the failure this whole
section is about: a dump restores the *catalogue*, and without the volume every
book in it is unopenable.

Finally, drop the scratch database:

```bash
docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" restore_drill'
```

### Rehearsing the whole thing

```bash
./deploy/deploy.sh drill
```

The manual steps below are worth understanding, but this performs the whole
sequence and cleans up after itself: the newest dump into a scratch database,
the library mirror into an empty directory, and then the check that matters —
that every storage key the restored database references has bytes on disk whose
SHA-256 is its own name.

That last step is the point. Restoring the two halves separately proves very
little; what you need to know is whether the catalogue and the files still
agree afterwards. Nothing live is touched, so it is safe to run whenever.

Restoring over the live database, when you actually need to, is
`./deploy/deploy.sh restore <file>` — which stops the app first and asks for
typed confirmation.

Putting the *files* back is separate:

```bash
./deploy/deploy.sh restore:library
```

It sends only what the server does not already have, and never overwrites: a
file already there has the contents its name says it has, so there is never a
reason to replace one. After a restore onto an empty server, re-render the
thumbnails:

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
cookie `Secure` flags off (plain HTTP) and enables registration. Never use it
on a server.

Backend tests:

```bash
docker compose run --rm --user root backend sh -c "pip install -q -r requirements-dev.txt && python -m pytest"
```

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `400 Bad Request` on every page | The MagicDNS name is missing from `DJANGO_ALLOWED_HOSTS`. |
| Login returns 200 but you stay signed out | `Secure` cookies over plain HTTP. Either finish the `tailscale serve` setup or set both `*_COOKIE_SECURE` to `False`. |
| `CSRF verification failed` | `DJANGO_CSRF_TRUSTED_ORIGINS` does not exactly match the origin in the browser, scheme included. |
| Deploy says it cannot reach the docker daemon | The `docker` group was just added. Disconnect and reconnect the SSH session once. |
| `tailscale serve` fails during bootstrap | HTTPS certificates are not enabled for the tailnet. Admin console → DNS → HTTPS Certificates. |
| Uploads fail with a 500 | A storage volume is not writable by the container. `entrypoint.sh` now refuses to start in that case and names the directory. |
| Uploads rejected with 507 | Disk is below `LUMA_MIN_FREE_DISK_BYTES`. Storage is canonical and cannot evict to recover — free space or add a disk. |
