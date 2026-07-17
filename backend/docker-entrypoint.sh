#!/bin/sh
set -eu

mkdir -p /app/data

# Keep compatibility with the original local layout: backend/app.db.
if [ ! -e /app/data/app.db ] && [ -f /app/legacy/app.db ]; then
    for suffix in '' '-wal' '-shm'; do
        if [ -f "/app/legacy/app.db${suffix}" ]; then
            cp "/app/legacy/app.db${suffix}" "/app/data/app.db${suffix}"
        fi
    done
    echo "Copied existing database from backend/app.db to data/app.db"
fi

exec "$@"
