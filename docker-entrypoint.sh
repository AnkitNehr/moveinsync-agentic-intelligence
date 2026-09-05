#!/bin/sh
# Ensure the state directory exists and is writable by the app user, then drop
# privileges. The outbox and incident memory live here; a read-only or root-owned
# bind mount would make the act loop look like it ran while writing nothing.
set -e

STATE_DIR="${APP_STATE_DIR:-/data/state}"
mkdir -p "$STATE_DIR"

if [ "$(id -u)" = "0" ]; then
    chown -R app:app "$STATE_DIR" 2>/dev/null || true
    exec gosu app java -jar /app/app.jar "$@"
fi

exec java -jar /app/app.jar "$@"
