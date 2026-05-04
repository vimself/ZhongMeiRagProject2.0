#!/usr/bin/env sh
set -eu

if [ "${RUN_ALEMBIC:-0}" = "1" ] && [ -f "alembic.ini" ]; then
  alembic upgrade head
fi

exec "$@"
