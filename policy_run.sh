#!/usr/bin/env bash
set -euo pipefail

RUN_ID="${1:-pr-1}"
shift || true

exec python3 policy_records_main.py \
  --run-id "$RUN_ID" \
  "$@"
