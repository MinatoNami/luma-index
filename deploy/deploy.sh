#!/usr/bin/env bash
#
# LumaIndex deploy driver. Runs on your laptop, does everything over SSH.
#
#   ./deploy/deploy.sh bootstrap        one-time server prep (docker, tailscale, ufw)
#   ./deploy/deploy.sh env:push         upload .env to the server (first run / after edits)
#   ./deploy/deploy.sh                  deploy the current working tree
#   ./deploy/deploy.sh status           what is running
#   ./deploy/deploy.sh logs [service]   tail logs
#   ./deploy/deploy.sh rollback         switch back to the previous release
#   ./deploy/deploy.sh backup [--download]
#   ./deploy/deploy.sh restore <file>
#   ./deploy/deploy.sh manage <args>    run a Django management command
#   ./deploy/deploy.sh createsuperuser
#   ./deploy/deploy.sh shell [service]
#   ./deploy/deploy.sh down
#
# Layout created on the server:
#
#   $DEPLOY_PATH/
#   ├── shared/.env            secrets, survives every deploy
#   ├── releases/<stamp>/      one directory per deploy
#   ├── current -> releases/…  what compose runs from
#   └── backups/               pg_dump output
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_FILE="${DEPLOY_CONFIG:-$REPO_ROOT/deploy/deploy.env}"

# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[34m'
else
    C_RESET=; C_BOLD=; C_DIM=; C_RED=; C_GREEN=; C_YELLOW=; C_BLUE=
fi

step() { printf '%s==>%s %s%s%s\n' "$C_BLUE" "$C_RESET" "$C_BOLD" "$*" "$C_RESET"; }
info() { printf '    %s\n' "$*"; }
dim()  { printf '    %s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }
warn() { printf '%s !! %s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
ok()   { printf '%s ✓ %s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
die()  { printf '%s ✗ %s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
load_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        die "No deploy config at $CONFIG_FILE
    Create it with:
      cp deploy/deploy.env.example deploy/deploy.env
      \$EDITOR deploy/deploy.env"
    fi
    set -a
    # shellcheck source=/dev/null
    . "$CONFIG_FILE"
    set +a

    : "${DEPLOY_HOST:?DEPLOY_HOST is not set in $CONFIG_FILE}"
    : "${DEPLOY_USER:?DEPLOY_USER is not set in $CONFIG_FILE}"
    DEPLOY_PORT="${DEPLOY_PORT:-22}"
    DEPLOY_PATH="${DEPLOY_PATH:-/opt/lumaindex}"
    DEPLOY_METHOD="${DEPLOY_METHOD:-rsync}"
    DEPLOY_GIT_REF="${DEPLOY_GIT_REF:-main}"
    DEPLOY_KEEP_RELEASES="${DEPLOY_KEEP_RELEASES:-5}"

    SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"

    # A shared connection turns ~12 SSH handshakes per deploy into one.
    CONTROL_PATH="${TMPDIR:-/tmp}/lumaindex-ssh-$(echo "$SSH_TARGET" | tr -c 'a-zA-Z0-9' '_')"
    SSH_OPTS=(-p "$DEPLOY_PORT"
              -o ControlMaster=auto
              -o "ControlPath=$CONTROL_PATH"
              -o ControlPersist=120
              -o ConnectTimeout=10)
    [ -n "${DEPLOY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$DEPLOY_SSH_KEY")
}

cleanup() {
    [ -n "${CONTROL_PATH:-}" ] && [ -S "$CONTROL_PATH" ] && \
        ssh -O exit -o "ControlPath=$CONTROL_PATH" "$SSH_TARGET" 2>/dev/null || true
}
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# SSH helpers
# --------------------------------------------------------------------------- #

# Run a command on the server.
rexec() { ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "$@"; }

# Run a script piped over stdin, with strict mode on the far side too.
rscript() { ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "bash -euo pipefail -s" ; }

# Run docker compose in the current release, with the shared .env.
rcompose() {
    rexec "cd '$DEPLOY_PATH/current' && docker compose --env-file '$DEPLOY_PATH/shared/.env' $*"
}

# Interactive variant (allocates a TTY) for shells and prompts.
rcompose_tty() {
    ssh -t "${SSH_OPTS[@]}" "$SSH_TARGET" \
        "cd '$DEPLOY_PATH/current' && docker compose --env-file '$DEPLOY_PATH/shared/.env' $*"
}

# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #
preflight() {
    step "Preflight"

    rexec true 2>/dev/null || die "Cannot SSH to $SSH_TARGET on port $DEPLOY_PORT.
    Check the host is up (tailscale status) and your key is loaded (ssh-add -l)."
    ok "SSH to $SSH_TARGET"

    rexec "command -v docker >/dev/null" \
        || die "docker is not installed on the server. Run: ./deploy/deploy.sh bootstrap"
    rexec "docker compose version >/dev/null 2>&1" \
        || die "The docker compose plugin is missing. Run: ./deploy/deploy.sh bootstrap"
    rexec "docker info >/dev/null 2>&1" \
        || die "$DEPLOY_USER cannot talk to the docker daemon.
    Run: ./deploy/deploy.sh bootstrap   (then log out and back in once)"
    ok "docker and compose usable as $DEPLOY_USER"

    rexec "test -f '$DEPLOY_PATH/shared/.env'" || die "No .env on the server.
    Create one locally and upload it:
      cp .env.example .env && \$EDITOR .env
      ./deploy/deploy.sh env:push"
    ok "shared/.env present"

    # Catch placeholder values before they cause a confusing 500 later.
    local placeholders
    placeholders="$(rexec "grep -c 'CHANGE_ME' '$DEPLOY_PATH/shared/.env' || true")"
    if [ "${placeholders:-0}" -gt 0 ]; then
        die "$placeholders CHANGE_ME placeholder(s) remain in the server's .env.
    Fix them locally and re-run: ./deploy/deploy.sh env:push"
    fi
    ok "no placeholder secrets"

    local free_kb
    free_kb="$(rexec "df -Pk '$DEPLOY_PATH' | awk 'NR==2 {print \$4}'")"
    if [ "${free_kb:-0}" -lt 2097152 ]; then
        warn "Less than 2 GiB free on $DEPLOY_PATH ($((free_kb / 1024)) MiB). \
Docker builds and the PDF cache both want room."
    else
        ok "$((free_kb / 1048576)) GiB free on $DEPLOY_PATH"
    fi

    if [ "$DEPLOY_METHOD" = "rsync" ] && ! git -C "$REPO_ROOT" diff --quiet HEAD 2>/dev/null; then
        warn "Working tree has uncommitted changes — they WILL be deployed."
    fi
}

# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

cmd_bootstrap() {
    step "Bootstrapping $SSH_TARGET"
    warn "This installs Docker, configures ufw, and enables tailscale serve. It needs sudo."
    rexec true 2>/dev/null || die "Cannot SSH to $SSH_TARGET."

    ssh -t "${SSH_OPTS[@]}" "$SSH_TARGET" \
        "sudo DEPLOY_PATH='$DEPLOY_PATH' DEPLOY_USER='$DEPLOY_USER' bash -s" \
        < "$REPO_ROOT/deploy/bootstrap.sh"

    ok "Bootstrap finished"
    info "Next:"
    info "  1. cp .env.example .env  &&  \$EDITOR .env"
    info "  2. ./deploy/deploy.sh env:push"
    info "  3. ./deploy/deploy.sh"
}

cmd_env_push() {
    local src="${1:-$REPO_ROOT/.env}"
    [ -f "$src" ] || die "No $src to upload. Start from: cp .env.example .env"

    if grep -q 'CHANGE_ME' "$src"; then
        grep -n 'CHANGE_ME' "$src" >&2
        die "Fill in the CHANGE_ME values above before uploading."
    fi

    step "Uploading $src -> $DEPLOY_PATH/shared/.env"
    rexec "mkdir -p '$DEPLOY_PATH/shared'"

    # Keep a timestamped copy of whatever is already there — a mistyped .env
    # push should not be the thing that loses your encryption key.
    rexec "test -f '$DEPLOY_PATH/shared/.env' && \
           cp -a '$DEPLOY_PATH/shared/.env' \
                 '$DEPLOY_PATH/shared/.env.bak.\$(date -u +%Y%m%dT%H%M%SZ)' || true"

    # Piped over the existing SSH connection: the secrets never touch a temp
    # file on the server and never appear in a process list.
    rexec "cat > '$DEPLOY_PATH/shared/.env' && chmod 600 '$DEPLOY_PATH/shared/.env'" < "$src"
    ok "Uploaded (mode 600)"
    dim "Reminder: LUMA_FIELD_ENCRYPTION_KEY must also live somewhere outside this server."
}

sync_code() {
    local release_dir="$1"

    case "$DEPLOY_METHOD" in
      rsync)
        step "Syncing working tree (rsync)"
        command -v rsync >/dev/null || die "rsync is not installed locally."
        rexec "mkdir -p '$release_dir'"
        rsync -az --delete \
            --exclude '.git/' \
            --exclude 'node_modules/' \
            --exclude '.nuxt/' --exclude '.output/' \
            --exclude '__pycache__/' --exclude '*.pyc' \
            --exclude '.venv/' --exclude '.pytest_cache/' --exclude '.ruff_cache/' \
            --exclude 'data/' --exclude 'backups/' \
            --exclude '.env' --exclude 'deploy/deploy.env' \
            -e "ssh ${SSH_OPTS[*]}" \
            "$REPO_ROOT/" "$SSH_TARGET:$release_dir/"
        ;;
      git)
        : "${DEPLOY_GIT_URL:?DEPLOY_GIT_URL must be set when DEPLOY_METHOD=git}"
        step "Fetching $DEPLOY_GIT_REF (git)"
        rscript <<REMOTE
mkdir -p '$release_dir'
git clone --depth 1 --branch '$DEPLOY_GIT_REF' '$DEPLOY_GIT_URL' '$release_dir'
rm -rf '$release_dir/.git'
REMOTE
        ;;
      *)
        die "Unknown DEPLOY_METHOD='$DEPLOY_METHOD' (expected 'rsync' or 'git')."
        ;;
    esac
    ok "Code in place"
}

wait_for_health() {
    step "Waiting for the app to report ready"
    local attempts=40
    for i in $(seq 1 "$attempts"); do
        if rexec "curl -fsS --max-time 5 http://127.0.0.1:${CADDY_HTTP_PORT:-8080}/api/health/ready/ >/dev/null 2>&1"; then
            ok "Healthy after ${i}0s or less"
            return 0
        fi
        sleep 5
    done
    return 1
}

cmd_deploy() {
    preflight

    local stamp sha release_dir previous_dir
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    sha="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit)"
    release_dir="$DEPLOY_PATH/releases/${stamp}-${sha}"
    previous_dir="$(rexec "readlink -f '$DEPLOY_PATH/current' 2>/dev/null || true")"

    step "Deploying ${stamp}-${sha}"
    info "target   $SSH_TARGET:$DEPLOY_PATH"
    info "method   $DEPLOY_METHOD"
    [ -n "$previous_dir" ] && info "previous $(basename "$previous_dir")"

    sync_code "$release_dir"

    step "Building images"
    rexec "cd '$release_dir' && LUMA_IMAGE_TAG='${stamp}-${sha}' \
           docker compose --env-file '$DEPLOY_PATH/shared/.env' build"
    ok "Images built"

    # Flip `current` only after a successful build, so a build failure leaves
    # the running release untouched.
    rexec "ln -sfn '$release_dir' '$DEPLOY_PATH/current.new' && \
           mv -Tf '$DEPLOY_PATH/current.new' '$DEPLOY_PATH/current'"

    step "Starting services (migrations run inside the backend entrypoint)"
    if ! rcompose "up -d --remove-orphans --wait --wait-timeout 180"; then
        warn "compose did not converge; showing recent backend logs"
        rcompose "logs --tail 60 backend" || true
    fi

    if wait_for_health; then
        rcompose "ps"
        prune_releases "$release_dir"
        step "Done"
        ok "$(grep -E '^LUMA_PUBLIC_ORIGIN=' "$REPO_ROOT/.env" 2>/dev/null | cut -d= -f2- || echo 'App')"
        return 0
    fi

    warn "The new release never became ready."
    rcompose "logs --tail 80 backend" || true

    if [ -n "$previous_dir" ] && [ "$previous_dir" != "$release_dir" ]; then
        warn "Rolling back to $(basename "$previous_dir")"
        rexec "ln -sfn '$previous_dir' '$DEPLOY_PATH/current.new' && \
               mv -Tf '$DEPLOY_PATH/current.new' '$DEPLOY_PATH/current'"
        rcompose "up -d --wait --wait-timeout 180" || true
        warn "Code rolled back. NOTE: database migrations are NOT reversed —
    if this release migrated the schema, the old code may not run against it.
    Check with: ./deploy/deploy.sh logs backend"
    fi
    die "Deploy failed."
}

prune_releases() {
    local keep="$DEPLOY_KEEP_RELEASES"
    step "Pruning old releases (keeping $keep)"
    rscript <<REMOTE
cd '$DEPLOY_PATH/releases' 2>/dev/null || exit 0
current="\$(readlink -f '$DEPLOY_PATH/current' || true)"
ls -1dt */ 2>/dev/null | tail -n +\$(( $keep + 1 )) | while read -r old; do
    old_abs="\$(readlink -f "\$old")"
    [ "\$old_abs" = "\$current" ] && continue
    rm -rf -- "\$old_abs"
    echo "    removed \$old"
done
REMOTE
    # Dangling images from previous builds add up fast on a small server.
    rexec "docker image prune -f --filter 'dangling=true' >/dev/null" || true
    ok "Pruned"
}

cmd_rollback() {
    step "Rolling back"
    local target
    target="$(rexec "ls -1dt '$DEPLOY_PATH'/releases/*/ 2>/dev/null | sed -n 2p || true")"
    [ -n "$target" ] || die "No previous release to roll back to."

    info "Switching to $(basename "${target%/}")"
    warn "This reverts CODE only. Applied database migrations stay applied."
    printf '    Continue? [y/N] '
    read -r reply
    [ "$reply" = "y" ] || [ "$reply" = "Y" ] || die "Aborted."

    rexec "ln -sfn '${target%/}' '$DEPLOY_PATH/current.new' && \
           mv -Tf '$DEPLOY_PATH/current.new' '$DEPLOY_PATH/current'"
    rcompose "up -d --wait --wait-timeout 180"
    wait_for_health && ok "Rolled back" || die "Rollback did not become healthy."
}

cmd_status() {
    step "Release"
    rexec "readlink -f '$DEPLOY_PATH/current' | xargs basename" || true
    step "Services"
    rcompose "ps"
    step "Health"
    rexec "curl -fsS --max-time 5 http://127.0.0.1:${CADDY_HTTP_PORT:-8080}/api/health/ready/" \
        || warn "readiness endpoint is not responding"
    echo
    step "Disk"
    rexec "df -h '$DEPLOY_PATH' | tail -1"
    rexec "docker system df" || true
}

cmd_logs() {
    local service="${1:-}"
    rcompose_tty "logs -f --tail 200 $service"
}

cmd_backup() {
    local download=0
    [ "${1:-}" = "--download" ] && download=1

    local stamp file
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    file="lumaindex-${stamp}.sql.gz"

    step "Dumping PostgreSQL"
    rexec "mkdir -p '$DEPLOY_PATH/backups'"
    # -Fc would be smaller, but plain SQL survives a Postgres major-version
    # change, which is exactly when you most need the backup to work.
    rcompose "exec -T postgres sh -c 'pg_dump -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" --clean --if-exists'" \
        | gzip -c > "/tmp/$file"

    local size
    size="$(wc -c < "/tmp/$file")"
    [ "$size" -gt 1000 ] || die "Dump is only ${size} bytes — something went wrong."

    rexec "cat > '$DEPLOY_PATH/backups/$file'" < "/tmp/$file"
    ok "Server copy: $DEPLOY_PATH/backups/$file ($((size / 1024)) KiB)"

    if [ "$download" = "1" ]; then
        mkdir -p "$REPO_ROOT/backups"
        mv "/tmp/$file" "$REPO_ROOT/backups/$file"
        ok "Local copy: backups/$file"
    else
        rm -f "/tmp/$file"
        dim "Pass --download to also keep a copy on this machine."
    fi

    warn "This dump does NOT contain LUMA_FIELD_ENCRYPTION_KEY. Without that key
    the encrypted OAuth tokens inside it are unreadable — store the key separately."
}

cmd_restore() {
    local file="${1:-}"
    [ -n "$file" ] || die "Usage: ./deploy/deploy.sh restore <backup.sql.gz>"
    [ -f "$file" ] || die "No such file: $file"

    warn "RESTORE IS DESTRUCTIVE."
    info "This drops and recreates every table in the live database from:"
    info "  $file"
    printf "    Type 'restore' to continue: "
    read -r reply
    [ "$reply" = "restore" ] || die "Aborted."

    step "Stopping application containers (leaving postgres up)"
    rcompose "stop backend frontend caddy"

    step "Restoring"
    gunzip -c "$file" | rcompose "exec -T postgres sh -c 'psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\"'"

    step "Starting application containers"
    rcompose "up -d --wait --wait-timeout 180"
    wait_for_health && ok "Restored" || die "App did not become healthy after restore."
}

cmd_manage() {
    [ "$#" -gt 0 ] || die "Usage: ./deploy/deploy.sh manage <django command> [args]"
    rcompose_tty "exec backend python manage.py $*"
}

cmd_createsuperuser() {
    rcompose_tty "exec backend python manage.py createsuperuser"
}

cmd_shell() {
    local service="${1:-backend}"
    rcompose_tty "exec $service sh"
}

cmd_down() {
    warn "This stops LumaIndex. Data volumes are kept."
    printf '    Continue? [y/N] '
    read -r reply
    [ "$reply" = "y" ] || [ "$reply" = "Y" ] || die "Aborted."
    rcompose "down"
    ok "Stopped"
}

usage() {
    # Print the header comment block and stop at the first line that is not a
    # comment, so the help text cannot drift out of sync with the script.
    awk 'NR>2 { if ($0 !~ /^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
}

# --------------------------------------------------------------------------- #
main() {
    local command="${1:-deploy}"
    [ "$#" -gt 0 ] && shift || true

    case "$command" in
        -h|--help|help) usage; exit 0 ;;
    esac

    load_config

    case "$command" in
        deploy)          cmd_deploy "$@" ;;
        bootstrap)       cmd_bootstrap "$@" ;;
        env:push)        cmd_env_push "$@" ;;
        status)          cmd_status "$@" ;;
        logs)            cmd_logs "$@" ;;
        rollback)        cmd_rollback "$@" ;;
        backup)          cmd_backup "$@" ;;
        restore)         cmd_restore "$@" ;;
        manage)          cmd_manage "$@" ;;
        createsuperuser) cmd_createsuperuser "$@" ;;
        migrate)         cmd_manage migrate ;;
        shell)           cmd_shell "$@" ;;
        down)            cmd_down "$@" ;;
        *) die "Unknown command '$command'. Run --help for the list." ;;
    esac
}

main "$@"
