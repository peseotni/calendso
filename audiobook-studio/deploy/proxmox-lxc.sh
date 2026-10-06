#!/usr/bin/env bash
# Create a Proxmox VE LXC container running Audiobook Studio.
# Run on the Proxmox host from an Audiobook Studio checkout:
#
#     ./deploy/proxmox-lxc.sh
#
# Settings (environment variables):
#     CTID       container id            (default: next free id)
#     CT_HOSTNAME container hostname     (default: audiobook-studio)
#     STORAGE    rootfs storage          (default: local-lvm)
#     DISK       rootfs size in GB       (default: 16)
#     CORES      CPU cores               (default: 4)
#     MEMORY     RAM in MB               (default: 4096)
#     BRIDGE     network bridge          (default: vmbr0)
#     TEMPLATE_STORAGE  storage for container templates (default: local)
#     MEDIA_DIR  optional host folder bind-mounted as /srv/audiobooks
set -euo pipefail

CTID="${CTID:-$(pvesh get /cluster/nextid)}"
CT_HOSTNAME="${CT_HOSTNAME:-audiobook-studio}"
STORAGE="${STORAGE:-local-lvm}"
DISK="${DISK:-16}"
CORES="${CORES:-4}"
MEMORY="${MEMORY:-4096}"
BRIDGE="${BRIDGE:-vmbr0}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

command -v pct >/dev/null || { echo "This script must run on a Proxmox VE host." >&2; exit 1; }

echo "==> Looking for a Debian 12 container template"
pveam update >/dev/null
TEMPLATE="$(pveam available --section system | awk '{print $2}' | grep -E '^debian-12-standard_.*_amd64\.tar\.(zst|gz|xz)$' | sort -V | tail -n1)"
[ -n "$TEMPLATE" ] || { echo "No Debian 12 template found" >&2; exit 1; }
if ! pveam list "$TEMPLATE_STORAGE" | grep -q "$TEMPLATE"; then
    pveam download "$TEMPLATE_STORAGE" "$TEMPLATE"
fi

echo "==> Creating container $CTID ($CT_HOSTNAME)"
pct create "$CTID" "$TEMPLATE_STORAGE:vztmpl/$TEMPLATE" \
    --hostname "$CT_HOSTNAME" \
    --cores "$CORES" \
    --memory "$MEMORY" \
    --swap 1024 \
    --rootfs "$STORAGE:$DISK" \
    --net0 "name=eth0,bridge=$BRIDGE,ip=dhcp" \
    --unprivileged 1 \
    --features nesting=1 \
    --onboot 1
if [ -n "${MEDIA_DIR:-}" ]; then
    pct set "$CTID" --mp0 "$MEDIA_DIR,mp=/srv/audiobooks"
fi
pct start "$CTID"

echo "==> Waiting for the network"
for _ in $(seq 1 60); do
    if pct exec "$CTID" -- sh -c 'getent hosts deb.debian.org >/dev/null 2>&1'; then break; fi
    sleep 2
done

echo "==> Copying Audiobook Studio into the container"
archive="$(mktemp --suffix=.tar.gz)"
tar -C "$SOURCE_DIR" --exclude=node_modules --exclude=data --exclude=__pycache__ -czf "$archive" .
pct push "$CTID" "$archive" /root/audiobook-studio.tar.gz
rm -f "$archive"
pct exec "$CTID" -- bash -c 'mkdir -p /root/audiobook-studio && tar -xzf /root/audiobook-studio.tar.gz -C /root/audiobook-studio'

echo "==> Running the installer inside the container"
pct exec "$CTID" -- bash -c 'apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null && bash /root/audiobook-studio/deploy/install.sh'

ip="$(pct exec "$CTID" -- hostname -I | awk '{print $1}')"
echo
echo "==> Done! Open http://$ip:8000"
