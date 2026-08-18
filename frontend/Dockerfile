# syntax=docker/dockerfile:1

# --- build ------------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
# `npm ci` needs a lockfile; fall back to `install` so a fresh clone still builds.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .

# PDF.js needs its character maps to render CJK text; without them those pages
# come out blank. They live in node_modules, so they are copied into the static
# directory here rather than committed.
RUN mkdir -p public/cmaps \
 && cp -r node_modules/pdfjs-dist/cmaps/. public/cmaps/

RUN npm run build

# --- runtime ----------------------------------------------------------------
FROM node:22-alpine AS runtime

ENV NODE_ENV=production \
    NITRO_PORT=3000 \
    NITRO_HOST=0.0.0.0

RUN apk add --no-cache curl

WORKDIR /app

# Nitro's output is fully self-contained — no node_modules needed at runtime.
COPY --from=build --chown=node:node /app/.output /app/.output

USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:3000/login || exit 1

CMD ["node", ".output/server/index.mjs"]
