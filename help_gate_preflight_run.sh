#!/usr/bin/env bash
set -euo pipefail

LANG="${1:-zh}"
RUN_ID="${2:-hg-1}"
QA_RUN_ID="${3:-}"
POLICY_RUN_ID="${4:-}"

if [ -z "${QA_RUN_ID}" ] || [ -z "${POLICY_RUN_ID}" ]; then
  echo "Usage: $0 <lang> <run_id> <qa_run_id> <policy_run_id> [extra args...]" >&2
  exit 1
fi

shift 4

exec python3 help_gate_main.py preflight \
  --language "$LANG" \
  --run-id "$RUN_ID" \
  --qa-run-id "$QA_RUN_ID" \
  --policy-run-id "$POLICY_RUN_ID" \
  "$@"
