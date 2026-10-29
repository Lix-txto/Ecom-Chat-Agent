#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec uv run celery -A app.celery_app:celery_app worker --loglevel=info --concurrency=2 "$@"
