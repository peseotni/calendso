#!/usr/bin/env bash
# Audiobook Studio installer for Debian / Ubuntu – bare metal, VMs and LXC
# containers (Proxmox, LXD/Incus). Run it as root from a checkout:
#
#     sudo ./deploy/install.sh
#
# Re-running the script upgrades an existing installation in place; your data
# and audiobooks are kept. Behaviour can be tuned with environment variables:
#
#     STUDIO_PORT=8000                 web port
#     INSTALL_DIR=/opt/audiobook-studio
#     DATA_DIR=/var/lib/audiobook-studio
#     LIBRARY_DIR=/srv/audiobooks      finished audiobooks
#     SERVICE_USER=audiobook
#     OCR_LANGS="eng"                  Tesseract language packs ("" disables OCR)
#     NODE_VERSION=22                  Node.js major used to build the web UI
set -euo pipefail

STUDIO_PORT="${STUDIO_PORT:-8000}"
INSTALL_DIR="${INSTALL_DIR:-/opt/audiobook-studio}"
DATA_DIR="${DATA_DIR:-/var/lib/audiobook-studio}"
LIBRARY_DIR="${LIBRARY_DIR:-/srv/audiobooks}"
SERVICE_USER="${SERVICE_USER:-audiobook}"
OCR_LANGS="${OCR_LANGS-eng}"
NODE_VERSION="${NODE_VERSION:-22}"
ENV_FILE="/etc/audiobook-studio.env"
SERVICE_FILE="/etc/systemd/system/audiobook-studio.service"

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# On upgrades the existing configuration file is the source of truth.
if [ -f "$ENV_FILE" ]; then
    env_value() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n1; }
    STUDIO_PORT="$(env_value STUDIO_PORT)"; STUDIO_PORT="${STUDIO_PORT:-8000}"
    configured_data="$(env_value STUDIO_DATA_DIR)"; DATA_DIR="${configured_data:-$DATA_DIR}"
    configured_library="$(env_value STUDIO_LIBRARY_DIR)"; LIBRARY_DIR="${configured_library:-$LIBRARY_DIR}"
fi

info() { printf '\033[1;35m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "please run as root (sudo $0)"
[ -f "$SOURCE_DIR/backend/requirements.txt" ] || die "run this script from an Audiobook Studio checkout"
command -v apt-get >/dev/null || die "this installer supports Debian/Ubuntu (apt) only"

# ------------------------------------------------------------------ packages
info "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
packages=(python3 python3-venv python3-pip ffmpeg espeak-ng ca-certificates curl xz-utils)
if [ -n "$OCR_LANGS" ]; then
    packages+=(tesseract-ocr)
    for lang in $OCR_LANGS; do packages+=("tesseract-ocr-$lang"); done
fi
apt-get install -y -qq --no-install-recommends "${packages[@]}" >/dev/null

PYTHON=python3
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    # Ubuntu 22.04 ships Python 3.10 but offers 3.11 as an extra package.
    if apt-cache show python3.11-venv >/dev/null 2>&1; then
        info "Installing Python 3.11"
        apt-get install -y -qq --no-install-recommends python3.11 python3.11-venv >/dev/null
        PYTHON=python3.11
    else
        die "Python 3.11 or newer is required (Debian 12+, Ubuntu 22.04+)"
    fi
fi

# ------------------------------------------------------------------ web UI
NODE_TMP=""
cleanup() { [ -n "$NODE_TMP" ] && rm -rf "$NODE_TMP"; }
trap cleanup EXIT

if [ -f "$SOURCE_DIR/frontend/dist/index.html" ] && [ "${REBUILD_UI:-0}" != "1" ]; then
    info "Using the prebuilt web UI"
else
    node_bin=""
    if command -v node >/dev/null && [ "$(node -p 'process.versions.node.split(".")[0]')" -ge 20 ]; then
        node_bin="$(dirname "$(command -v node)")"
    else
        info "Downloading Node.js $NODE_VERSION (only needed to build the web UI)"
        case "$(uname -m)" in
            x86_64) node_arch=x64 ;;
            aarch64 | arm64) node_arch=arm64 ;;
            armv7l) node_arch=armv7l ;;
            *) die "unsupported CPU architecture $(uname -m)" ;;
        esac
        NODE_TMP="$(mktemp -d)"
        base="https://nodejs.org/dist/latest-v${NODE_VERSION}.x"
        tarball="$(curl -fsSL "$base/SHASUMS256.txt" | awk '{print $2}' | grep -E "^node-v[0-9.]+-linux-${node_arch}\.tar\.xz$" | head -n1)"
        [ -n "$tarball" ] || die "could not find a Node.js $NODE_VERSION download for $node_arch"
        curl -fsSL "$base/$tarball" | tar -xJ -C "$NODE_TMP" --strip-components=1
        node_bin="$NODE_TMP/bin"
    fi
    info "Building the web UI"
    (
        cd "$SOURCE_DIR/frontend"
        PATH="$node_bin:$PATH" npm ci --no-audit --no-fund --no-update-notifier --loglevel=error
        PATH="$node_bin:$PATH" npm run build --silent
    )
fi

# ------------------------------------------------------------------ application
info "Installing into $INSTALL_DIR"
id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$LIBRARY_DIR"

rm -rf "$INSTALL_DIR/app.new"
mkdir -p "$INSTALL_DIR/app.new"
cp -r "$SOURCE_DIR/backend/audiobook_studio" "$SOURCE_DIR/backend/pyproject.toml" "$SOURCE_DIR/backend/requirements.txt" "$INSTALL_DIR/app.new/"
rm -rf "$INSTALL_DIR/app.new/audiobook_studio/static"
cp -r "$SOURCE_DIR/frontend/dist" "$INSTALL_DIR/app.new/audiobook_studio/static"
find "$INSTALL_DIR/app.new" -name '__pycache__' -prune -exec rm -rf {} +

if [ -x "$INSTALL_DIR/venv/bin/python" ] && ! "$INSTALL_DIR/venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    rm -rf "$INSTALL_DIR/venv"
fi
if [ ! -x "$INSTALL_DIR/venv/bin/python" ]; then
    info "Creating Python environment"
    "$PYTHON" -m venv "$INSTALL_DIR/venv"
fi
info "Installing Python packages (this can take a few minutes)"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/app.new/requirements.txt"

rm -rf "$INSTALL_DIR/app.old"
[ -d "$INSTALL_DIR/app" ] && mv "$INSTALL_DIR/app" "$INSTALL_DIR/app.old"
mv "$INSTALL_DIR/app.new" "$INSTALL_DIR/app"
rm -rf "$INSTALL_DIR/app.old"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"
chown "$SERVICE_USER:$SERVICE_USER" "$LIBRARY_DIR"

# ------------------------------------------------------------------ configuration
if [ ! -f "$ENV_FILE" ]; then
    info "Writing $ENV_FILE"
    cat >"$ENV_FILE" <<EOF
# Audiobook Studio configuration – restart the service after changes:
#   systemctl restart audiobook-studio
STUDIO_HOST=0.0.0.0
STUDIO_PORT=$STUDIO_PORT
STUDIO_DATA_DIR=$DATA_DIR
STUDIO_LIBRARY_DIR=$LIBRARY_DIR
# STUDIO_INBOX_DIR=$DATA_DIR/inbox
# STUDIO_PASSWORD=change-me
# STUDIO_RENDER_WORKERS=1
EOF
fi

cat >"$INSTALL_DIR/run.sh" <<EOF
#!/bin/sh
# Start Audiobook Studio in the foreground (used when systemd is unavailable).
set -a
. "$ENV_FILE"
set +a
cd "$INSTALL_DIR/app"
exec "$INSTALL_DIR/venv/bin/python" -m audiobook_studio
EOF
chmod +x "$INSTALL_DIR/run.sh"

if [ -d /run/systemd/system ]; then
    info "Installing systemd service"
    cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Audiobook Studio
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
EnvironmentFile=$ENV_FILE
Environment=HOME=$DATA_DIR
WorkingDirectory=$INSTALL_DIR/app
ExecStart=$INSTALL_DIR/venv/bin/python -m audiobook_studio
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --quiet audiobook-studio
    systemctl restart audiobook-studio
    info "Waiting for the service to start"
    for _ in $(seq 1 30); do
        if curl -fsS "http://127.0.0.1:$STUDIO_PORT/api/health" >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    systemctl --no-pager --lines=0 status audiobook-studio || true
else
    warn "systemd not detected – start the server with: su -s /bin/sh $SERVICE_USER -c $INSTALL_DIR/run.sh"
fi

address="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
info "Audiobook Studio is installed: http://${address:-localhost}:$STUDIO_PORT"
echo "    data:       $DATA_DIR"
echo "    audiobooks: $LIBRARY_DIR"
echo "    settings:   $ENV_FILE"
echo "    logs:       journalctl -u audiobook-studio -f"
