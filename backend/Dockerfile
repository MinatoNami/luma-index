# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# `postgresql-client` gives us pg_dump/psql inside the container, which is what
# `deploy.sh backup` and `deploy.sh restore` shell into.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        curl \
        postgresql-client \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# Non-root (PRD §32). The UID is fixed so that named-volume ownership stays
# stable across image rebuilds.
RUN groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --home /app --no-create-home app

COPY --chown=app:app . /app

# Pre-creating these in the image means a *named volume* mounted here inherits
# app:app ownership on first creation. A bind mount does not — chown it on the
# host yourself if you switch to one.
RUN mkdir -p /data/pdf-cache /data/thumbnails /app/staticfiles \
 && chown -R app:app /data /app/staticfiles

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health/ || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
