#!/bin/sh
# Container entrypoint: prepares the data folders and optionally drops
# privileges to PUID/PGID so files on bind mounts get the right owner.
set -e

DATA_DIR="${STUDIO_DATA_DIR:-/data}"
LIBRARY_DIR="${STUDIO_LIBRARY_DIR:-/audiobooks}"
INBOX_DIR="${STUDIO_INBOX_DIR:-$DATA_DIR/inbox}"
MODELS_DIR="${STUDIO_MODELS_DIR:-$DATA_DIR/models}"

mkdir -p "$DATA_DIR" "$LIBRARY_DIR" "$INBOX_DIR" "$MODELS_DIR"
umask "${UMASK:-022}"

if [ "$(id -u)" = "0" ] && [ -n "${PUID:-}" ]; then
    PGID="${PGID:-$PUID}"
    # The application folders are small; the library is only fixed at the top level.
    chown -R "$PUID:$PGID" "$DATA_DIR" 2>/dev/null || echo "warning: could not chown $DATA_DIR"
    chown "$PUID:$PGID" "$LIBRARY_DIR" "$INBOX_DIR" 2>/dev/null || true
    export HOME="$DATA_DIR/.home"
    mkdir -p "$HOME" && chown "$PUID:$PGID" "$HOME"
    echo "Starting Audiobook Studio as uid=$PUID gid=$PGID"
    exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
fi

exec "$@"
