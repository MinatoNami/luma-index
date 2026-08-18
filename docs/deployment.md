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

## Backups

`deploy.sh backup` runs `pg_dump --clean --if-exists` inside the postgres
container and writes a gzipped plain-SQL dump to `/opt/lumaindex/backups/`.
Plain SQL rather than a custom-format dump on purpose: it still restores after
a PostgreSQL major-version change, which is exactly when you need it most.

Two things the dump does **not** contain:

- `LUMA_FIELD_ENCRYPTION_KEY`. Without it the encrypted OAuth tokens in the
  dump are unreadable. Keep the key in a password manager. Keeping it *only*
  next to the backup defeats the point of encrypting the column.
- The PDF cache and thumbnails. Both regenerate from Drive; PRD §38 says not to
  back them up, and they are the bulk of the disk.

A restore you have never tested is a hypothesis. Test it:

```bash
./deploy/deploy.sh backup --download
```

```bash
./deploy/deploy.sh restore backups/lumaindex-<timestamp>.sql.gz
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
| Sync stops working about weekly | Google OAuth consent screen is in Testing mode; refresh tokens expire after 7 days. See [google-oauth.md](google-oauth.md). |
