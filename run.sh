#!/usr/bin/env bash
set -euo pipefail

LANG="${1:-zh}"
OUTDIR="${2:-./output/${LANG}}"

exec python3 main.py \
  --max-depth 3 \
  --questions-per-node 5 \
  --model-catalog deepseek-v4-flash \
  --model-questions deepseek-v4-flash \
  --model-answers deepseek-v4-pro \
  --output-dir "$OUTDIR" \
  --language "$LANG"
