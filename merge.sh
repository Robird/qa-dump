#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "Usage: $0 OUTPUT_DIR INPUT [INPUT ...]" >&2
  exit 1
fi

OUTDIR="$1"
shift

exec python3 merge_runs.py --output-dir "$OUTDIR" "$@"
