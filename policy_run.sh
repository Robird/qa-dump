#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage:
  policy_run.sh [records] <run_id> [output_dir] [extra args...]
  policy_run.sh text <lang> <run_id> <policy_run_id> [output_dir] [extra args...]
EOF
  exit 1
}

MODE="records"
if [ "${1:-}" = "records" ] || [ "${1:-}" = "text" ]; then
  MODE="$1"
  shift
fi

case "$MODE" in
  records)
    RUN_ID="${1:-pr-1}"
    DEFAULT_OUTDIR="./output/shared/runs/policy_records--${RUN_ID}"

    if [ "${2:-}" != "" ] && [[ "${2}" != --* ]]; then
      OUTDIR="$2"
      shift_count=2
    else
      OUTDIR="${DEFAULT_OUTDIR}"
      shift_count=$(( $# >= 1 ? 1 : $# ))
    fi

    shift "${shift_count}"

    exec python3 policy_records_main.py \
      --run-id "$RUN_ID" \
      --output-dir "$OUTDIR" \
      "$@"
    ;;

  text)
    LANG="${1:-zh}"
    RUN_ID="${2:-pt-1}"
    POLICY_RUN_ID="${3:-}"
    DEFAULT_OUTDIR="./output/${LANG}/runs/policy_text_records--${RUN_ID}"

    if [ -z "${POLICY_RUN_ID}" ]; then
      usage
    fi

    if [ "${4:-}" != "" ] && [[ "${4}" != --* ]]; then
      OUTDIR="$4"
      shift_count=4
    else
      OUTDIR="${DEFAULT_OUTDIR}"
      shift_count=$(( $# >= 3 ? 3 : $# ))
    fi

    shift "${shift_count}"

    exec python3 policy_text_records_main.py \
      --run-id "$RUN_ID" \
      --policy-run-id "$POLICY_RUN_ID" \
      --language "$LANG" \
      --output-dir "$OUTDIR" \
      "$@"
    ;;

  *)
    usage
    ;;
esac
