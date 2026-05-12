#!/usr/bin/env bash
set -euo pipefail

LANG="${1:-zh}"
RUN_ID="${2:-hg-acml-1}"
QA_RUN_ID="${3:-}"
POLICY_TEXT_RUN_ID="${4:-}"
DEFAULT_OUTDIR="./output/${LANG}/runs/help_gate_acml--${RUN_ID}"

if [ -z "${QA_RUN_ID}" ] || [ -z "${POLICY_TEXT_RUN_ID}" ]; then
  echo "Usage: $0 <lang> <run_id> <qa_run_id> <policy_text_run_id> [output_dir] [extra args...]" >&2
  exit 1
fi

if [ "${5:-}" != "" ] && [[ "${5}" != --* ]]; then
  OUTDIR="$5"
  shift_count=5
else
  OUTDIR="${DEFAULT_OUTDIR}"
  shift_count=$(( $# >= 4 ? 4 : $# ))
fi

shift "${shift_count}"

exec python3 help_gate_main.py \
  --run-id "$RUN_ID" \
  --qa-run-id "$QA_RUN_ID" \
  --policy-text-run-id "$POLICY_TEXT_RUN_ID" \
  --language "$LANG" \
  --output-dir "$OUTDIR" \
  "$@"
