#!/usr/bin/env sh
set -eu

if [ "${RUN_ALEMBIC:-0}" = "1" ] && [ -f "alembic.ini" ]; then
  alembic upgrade head
fi

if [ "${SEED_DEFAULT_USERS:-0}" = "1" ]; then
  python -m app.cli.seed_default_users
fi

exec "$@"
