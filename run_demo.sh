#!/usr/bin/env bash
set -eo pipefail
cd "$(dirname "$0")"
source scripts/env.sh
exec python -u scripts/run_demo.py "$@"
