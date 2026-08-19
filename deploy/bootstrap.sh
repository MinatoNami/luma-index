#!/usr/bin/env bash
#
# One-time Ubuntu server preparation for LumaIndex.
#
# Runs ON THE SERVER as root. You normally invoke it from your laptop:
#
#     ./deploy/deploy.sh bootstrap
#
# It is idempotent — re-running it is safe and is the way to repair a server.
#
# What it does:
#   1. installs Docker Engine + the compose plugin from Docker's own repo
#   2. adds the deploy user to the docker group
#   3. creates /opt/lumaindex/{releases,shared,backups}
#   4. locks the firewall down to SSH + the tailnet
#   5. enables unattended security upgrades
#   6. points `tailscale serve` at Caddy so the app gets real HTTPS
#
set -euo pipefail

# NOT SAFE ON A SHARED HOST. This assumes the machine is LumaIndex's: it
# rewrites ufw's rules, may restart the Docker daemon (bouncing every container
# on the box, not just ours), and points `tailscale serve` at port 443.
#
# On a server already running something else, skip this and do the three things
# it exists for by hand:
#
#   1. install docker + compose, and put the deploy user in the docker group
#   2. sudo mkdir -p $DEPLOY_PATH/{releases,shared,backups} && chown it to that user
#   3. tailscale serve --bg --https=<free port> http://127.0.0.1:8080
#
# That is exactly how alena-server was set up, where nginx already owned 443
# and four unrelated containers had been up for weeks.

DEPLOY_PATH="${DEPLOY_PATH:-/opt/lumaindex}"
DEPLOY_USER="${DEPLOY_USER:-ubuntu}"
CADDY_PORT="${CADDY_HTTP_PORT:-8080}"

step() { printf '\n\033[34m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[33m !! \033[0m %s\n' "$*" >&2; }
ok()   { printf '\033[32m ✓ \033[0m %s\n' "$*"; }
die()  { printf '\033[31m ✗ \033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "bootstrap.sh must run as root (deploy.sh uses sudo for you)."

step "Checking the host"
. /etc/os-release 2>/dev/null || die "Cannot read /etc/os-release."
info "$PRETTY_NAME ($(uname -m))"
[ "${ID:-}" = "ubuntu" ] || warn "Tested on Ubuntu; '$ID' may behave differently."
id "$DEPLOY_USER" >/dev/null 2>&1 || die "User '$DEPLOY_USER' does not exist on this host."

export DEBIAN_FRONTEND=noninteractive

step "Installing base packages"
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg ufw rsync >/dev/null
ok "base packages"

# --------------------------------------------------------------------------- #
step "Docker Engine"
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    ok "already installed ($(docker --version))"
else
    # Ubuntu's own docker.io package lags and ships no compose plugin.
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/ubuntu/gpg" \
        -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    cat > /etc/apt/sources.list.d/docker.list <<EOF
deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable
EOF
    apt-get update -qq
    apt-get install -y -qq \
        docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin >/dev/null
    ok "installed $(docker --version)"
fi

systemctl enable --now docker >/dev/null 2>&1 || true

# Container logs are the default way to lose a disk on a small server.
if [ ! -f /etc/docker/daemon.json ]; then
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "5" }
}
EOF
    systemctl restart docker
    ok "docker log rotation configured"
fi

if id -nG "$DEPLOY_USER" | tr ' ' '\n' | grep -qx docker; then
    ok "$DEPLOY_USER is already in the docker group"
else
    usermod -aG docker "$DEPLOY_USER"
    ok "added $DEPLOY_USER to the docker group"
    warn "Group membership applies to NEW sessions. If the next deploy says it
    cannot reach the docker daemon, disconnect and reconnect once."
fi

# --------------------------------------------------------------------------- #
step "Directory layout"
mkdir -p "$DEPLOY_PATH"/{releases,shared,backups}
chown -R "$DEPLOY_USER":"$DEPLOY_USER" "$DEPLOY_PATH"
chmod 750 "$DEPLOY_PATH"
chmod 700 "$DEPLOY_PATH/shared" "$DEPLOY_PATH/backups"
ok "$DEPLOY_PATH ready"

# --------------------------------------------------------------------------- #
step "Firewall"
# The app itself binds to 127.0.0.1, so this is defence in depth rather than
# the only thing standing between LumaIndex and the internet.
ufw --force default deny incoming >/dev/null
ufw --force default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null 2>&1 || ufw allow 22/tcp >/dev/null
if ip link show tailscale0 >/dev/null 2>&1; then
    ufw allow in on tailscale0 >/dev/null
    ok "allowed: SSH, everything on tailscale0"
else
    warn "No tailscale0 interface yet — firewall allows SSH only for now."
fi
ufw --force enable >/dev/null
ok "ufw active"

# --------------------------------------------------------------------------- #
step "Unattended security upgrades"
apt-get install -y -qq unattended-upgrades >/dev/null
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
ok "enabled"

# --------------------------------------------------------------------------- #
step "Tailscale"
if ! command -v tailscale >/dev/null; then
    warn "Tailscale is not installed. Install and join the tailnet, then re-run bootstrap:"
    info "  curl -fsSL https://tailscale.com/install.sh | sh"
    info "  tailscale up"
elif ! tailscale status >/dev/null 2>&1; then
    warn "Tailscale is installed but not connected. Run:  tailscale up"
else
    ok "connected as $(tailscale status --json 2>/dev/null | grep -o '"DNSName":"[^"]*"' | head -1 | cut -d'"' -f4 || echo 'this node')"

    # `tailscale serve` terminates TLS with a real cert for the MagicDNS name
    # and forwards to Caddy on loopback. This is what makes Secure cookies work
    # without exposing a port to anything outside the tailnet.
    step "tailscale serve -> 127.0.0.1:$CADDY_PORT"
    if tailscale serve --bg --https=443 "http://127.0.0.1:${CADDY_PORT}" 2>/tmp/ts-serve.err; then
        ok "HTTPS is being terminated by Tailscale"
        tailscale serve status 2>/dev/null || true
    else
        warn "tailscale serve failed:"
        sed 's/^/    /' /tmp/ts-serve.err >&2 || true
        info "Most often this means HTTPS certificates are not enabled for the"
        info "tailnet. Enable them in the admin console under DNS > HTTPS"
        info "Certificates, then re-run: ./deploy/deploy.sh bootstrap"
        info ""
        info "To run without TLS instead, set both DJANGO_SESSION_COOKIE_SECURE"
        info "and DJANGO_CSRF_COOKIE_SECURE to False in .env — logins will not"
        info "work over plain HTTP while they are True."
    fi
fi

# --------------------------------------------------------------------------- #
step "Bootstrap complete"
info "Server:     $(hostname)"
info "Deploy dir: $DEPLOY_PATH"
info "Docker:     $(docker --version | cut -d, -f1)"
info ""
info "From your laptop:"
info "  ./deploy/deploy.sh env:push"
info "  ./deploy/deploy.sh"
