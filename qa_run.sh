#!/usr/bin/env bash
set -euo pipefail

LANG="${1:-zh}"
RUN_ID="${2:-default}"
DEFAULT_OUTDIR="./output/${LANG}/runs/qa_corpus--${RUN_ID}"

if [ "${3:-}" != "" ] && [[ "${3}" != --* ]]; then
  OUTDIR="$3"
  shift_count=3
else
  OUTDIR="${DEFAULT_OUTDIR}"
  shift_count=$(( $# >= 2 ? 2 : $# ))
fi

shift "${shift_count}"

exec python3 qa_main.py \
  --max-depth 3 \
  --questions-per-node 10 \
  --model-catalog deepseek-v4-flash \
  --model-questions deepseek-v4-flash \
  --model-answers deepseek-v4-pro \
  --run-id "$RUN_ID" \
  --output-dir "$OUTDIR" \
  --language "$LANG" \
  "$@"
