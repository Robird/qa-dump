#!/usr/bin/env python3
"""Shared implementation for derived-data task mains."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from pathlib import Path

from derived_lifecycle import DerivedTaskResult, run_derived_task
from derived_specs import POLICY_RECORDS_SPEC, POLICY_TEXT_RECORDS_SPEC
from derived_storage import DerivedRunState, DerivedStorageManager
from fs_utils import write_jsonl
from policy_generator import DEFAULT_PROFILE, PolicyGenerator
from policy_models import POLICY_GENERATOR_VERSION, PolicyRecord, make_policy_record_id, validate_policy_record
from policy_text_models import (
    make_policy_text_record_id,
    PolicyTextRecord,
    validate_policy_text_record,
)
from policy_text_preparation import (
    build_policy_text_record,
    prepare_policy_text_task,
    validate_policy_text_record_against_source,
)
from policy_text_realizer import PolicyTextRealizer
from policy_text_runtime import PolicyTextRuntimeConfig, build_policy_text_runtime
from run_metadata import load_config_doc, utc_now_iso
from run_paths import resolve_task_run_input
from run_resolver import resolve_existing_run
from task_contracts import (
    POLICY_TASK_FAMILY,
    make_artifact_ref,
    task_run_scope,
)

logger = logging.getLogger(__name__)


def _load_validated_policy_records(storage: DerivedStorageManager) -> list[PolicyRecord]:
    records: list[PolicyRecord] = []
    errors: list[str] = []
    for item_key in storage.list_existing_keys():
        raw = storage.read_item(item_key)
        if raw is None:
            errors.append(f"{item_key}: missing policy record payload")
            continue
        try:
            records.append(validate_policy_record(raw, expected_record_id=item_key))
        except Exception as exc:
            errors.append(f"{item_key}: {exc}")
    if errors:
        preview = "; ".join(errors[:3])
        extra = "" if len(errors) <= 3 else f" (+{len(errors) - 3} more)"
        raise ValueError(f"Policy-record artifact contract violations: {preview}{extra}")
    return records


def _rebuild_policy_records_export_view(storage: DerivedStorageManager) -> int:
    export_records = [record.model_dump() for record in _load_validated_policy_records(storage)]
    write_jsonl(storage.export_path(), export_records)
    return len(export_records)


def _load_validated_policy_text_records(storage: DerivedStorageManager) -> list[PolicyTextRecord]:
    records: list[PolicyTextRecord] = []
    errors: list[str] = []
    for item_key in storage.list_existing_keys():
        raw = storage.read_item(item_key)
        if raw is None:
            errors.append(f"{item_key}: missing policy_text payload")
            continue
        try:
            records.append(validate_policy_text_record(raw, expected_item_key=item_key))
        except Exception as exc:
            errors.append(f"{item_key}: {exc}")
    if errors:
        preview = "; ".join(errors[:3])
        extra = "" if len(errors) <= 3 else f" (+{len(errors) - 3} more)"
        raise ValueError(f"Policy-text contract violations: {preview}{extra}")
    return records


def _rebuild_policy_text_export_view(storage: DerivedStorageManager) -> int:
    export_records = [record.model_dump() for record in _load_validated_policy_text_records(storage)]
    write_jsonl(storage.export_path(), export_records)
    return len(export_records)


def _validate_existing_policy_text_records(storage: DerivedStorageManager) -> int:
    try:
        return len(_load_validated_policy_text_records(storage))
    except ValueError as exc:
        raise ValueError(
            str(exc).replace(
                "Policy-text contract violations",
                "Existing policy-text records failed validation",
            )
        ) from exc


def _validate_policy_text_records_against_source(
    storage: DerivedStorageManager,
    source_storage: DerivedStorageManager,
) -> int:
    records = _load_validated_policy_text_records(storage)
    errors: list[str] = []
    for record in records:
        raw = source_storage.read_item(record.source_policy_record_id)
        if raw is None:
            errors.append(f"{record.record_id}: missing source policy {record.source_policy_record_id}")
            continue
        try:
            source_policy = validate_policy_record(raw, expected_record_id=record.source_policy_record_id)
            validate_policy_text_record_against_source(record, source_policy)
        except Exception as exc:
            errors.append(f"{record.record_id}: {exc}")
    if errors:
        preview = "; ".join(errors[:3])
        extra = "" if len(errors) <= 3 else f" (+{len(errors) - 3} more)"
        raise ValueError(f"Existing policy-text records diverged from source policy records: {preview}{extra}")
    return len(records)


def _validate_policy_resume_config(run_dir: Path, args: argparse.Namespace) -> None:
    existing_config = load_config_doc(run_dir)
    if existing_config is None:
        return
    if existing_config.get("task") != "generate_policy_records":
        print(
            f"Cannot resume non-policy-record run in {run_dir}: "
            f"task={existing_config.get('task')!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    existing_seed = existing_config.get("seed")
    if existing_seed is not None and existing_seed != args.seed:
        print(
            f"Resume seed mismatch for {run_dir}: existing seed={existing_seed}, requested seed={args.seed}.\n"
            "Resume must use the same seed to keep policy-record ids deterministic.",
            file=sys.stderr,
        )
        sys.exit(1)
    existing_profile = existing_config.get("sampler_profile")
    if existing_profile is not None and existing_profile != DEFAULT_PROFILE.name:
        print(
            f"Resume sampler profile mismatch for {run_dir}: "
            f"existing profile={existing_profile}, requested profile={DEFAULT_PROFILE.name}.",
            file=sys.stderr,
        )
        sys.exit(1)
    existing_will_help_weight = existing_config.get("will_help_weight")
    if existing_will_help_weight is not None and existing_will_help_weight != args.will_help_weight:
        print(
            f"Resume will_help_weight mismatch for {run_dir}: "
            f"existing={existing_will_help_weight}, requested={args.will_help_weight}.",
            file=sys.stderr,
        )
        sys.exit(1)


def configure_logging(verbose: bool) -> None:
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def default_policy_run_dir(run_id: str) -> Path:
    return resolve_task_run_input(POLICY_TASK_FAMILY, run_id)


def get_llm_env() -> tuple[str, str]:
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("Error: DEEPSEEK_API_KEY environment variable is required.", file=sys.stderr)
        sys.exit(1)
    return base_url, api_key


def _write_policy_records(
    storage: DerivedStorageManager,
    records: list,
    existing_keys: set[str],
) -> int:
    written = 0
    for record in records:
        record = validate_policy_record(record, expected_record_id=record.record_id)
        if record.record_id in existing_keys:
            continue
        if not record.created_at:
            record.created_at = utc_now_iso()
        storage.write_item(record.record_id, record.model_dump())
        written += 1
    return written


def build_policy_records_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate first-class policy-record runs.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Current policy-record run id.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of policy records to generate",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible generation",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Explicit output directory for the current policy-record run",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume by skipping already-completed items",
    )
    parser.add_argument(
        "--will-help-weight",
        type=float,
        default=9.0,
        help=(
            "Relative weight for engage_now (will_help_now=True) decisions. "
            "1.0 = uniform (≈14%%); 3.0 ≈ 26%%; 5.0 ≈ 38%%. "
            "Other decisions keep weight 1.0."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging",
    )
    return parser


def build_policy_text_records_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate language-specific text realizations for policy records.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Current policy-text run id.",
    )
    parser.add_argument(
        "--policy-run-id",
        required=True,
        help="Source policy-record run id.",
    )
    parser.add_argument(
        "--policy-run-dir",
        default=None,
        help="Explicit source policy-record run directory.",
    )
    parser.add_argument(
        "--language",
        default="zh",
        choices=["zh", "en"],
        help="Output language for the text realizations.",
    )
    parser.add_argument(
        "--model",
        default="deepseek-v4-flash",
        help="Model used to realize belief/thinking text.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.8,
        help="Sampling temperature for text realization.",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Maximum number of source policy records to realize.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum realization attempts per source policy record.",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Model used for semantic judging; defaults to --model when omitted.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Explicit output directory for the current policy-text run",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume by skipping already-completed items",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=1,
        help="Maximum concurrent LLM workers for text realization",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging",
    )
    return parser


def _realize_one_policy_text(
    source_key: str,
    *,
    policy_storage: DerivedStorageManager,
    storage: DerivedStorageManager,
    base_url: str,
    api_key: str,
    language: str,
    runtime_config: PolicyTextRuntimeConfig,
    max_attempts: int,
    run_id: str,
    failure_lock: threading.Lock,
) -> dict:
    """Process a single policy text realization in a worker thread.

    Each worker creates its own LLM runtime so that the underlying httpx.Client
    is never shared across threads.
    """
    item_key = make_policy_text_record_id(source_key)
    raw = policy_storage.read_item(source_key)
    if raw is None:
        error_msg = f"Missing source policy record: {source_key}"
        with failure_lock:
            storage.append_failure(
                {
                    "task_name": POLICY_TEXT_RECORDS_SPEC.task_name,
                    "run_id": run_id,
                    "source_policy_record_id": source_key,
                    "item_key": item_key,
                    "failed_at": utc_now_iso(),
                    "error_type": "FileNotFoundError",
                    "error": error_msg,
                }
            )
        return {
            "source_key": source_key,
            "item_key": item_key,
            "success": False,
            "judge_rejections": 0,
            "error": error_msg,
            "policy_decision": "?",
            "will_help_now": None,
        }

    source_policy = validate_policy_record(raw, expected_record_id=source_key)
    if source_policy.record_id != source_key:
        error_msg = (
            f"Source policy record_id {source_policy.record_id!r} "
            f"does not match item key {source_key!r}"
        )
        with failure_lock:
            storage.append_failure(
                {
                    "task_name": POLICY_TEXT_RECORDS_SPEC.task_name,
                    "run_id": run_id,
                    "source_policy_record_id": source_key,
                    "item_key": item_key,
                    "failed_at": utc_now_iso(),
                    "error_type": "ValueError",
                    "error": error_msg,
                }
            )
        return {
            "source_key": source_key,
            "item_key": item_key,
            "success": False,
            "judge_rejections": 0,
            "error": error_msg,
            "policy_decision": raw.get("policy", {}).get("decision", "?"),
            "will_help_now": raw.get("policy", {}).get("decision") == "engage_now",
        }

    # Each worker owns its own LLM runtime so httpx.Client stays single-thread.
    with ExitStack() as stack:
        runtime = build_policy_text_runtime(
            stack,
            base_url=base_url,
            api_key=api_key,
            language=language,
            config=runtime_config,
        )
        realizer = PolicyTextRealizer(
            runtime.generator,
            semantic_judge=runtime.semantic_judge,
        )
        task = prepare_policy_text_task(source_policy, language=language)
        outcome = realizer.realize(task, max_attempts=max_attempts)

    if outcome.last_error is not None:
        with failure_lock:
            storage.append_failure(
                {
                    "task_name": POLICY_TEXT_RECORDS_SPEC.task_name,
                    "run_id": run_id,
                    "source_policy_record_id": source_policy.record_id,
                    "item_key": item_key,
                    "failed_at": utc_now_iso(),
                    "error_type": type(outcome.last_error).__name__,
                    "error": str(outcome.last_error),
                }
            )
        return {
            "source_key": source_key,
            "item_key": item_key,
            "success": False,
            "judge_rejections": outcome.judge_rejections,
            "error": str(outcome.last_error),
            "policy_decision": source_policy.policy.decision,
            "will_help_now": task.intent_spec.will_help_now,
        }

    if outcome.realization is None:
        error_msg = (
            f"Policy text realization unexpectedly missing for "
            f"{source_policy.record_id}"
        )
        with failure_lock:
            storage.append_failure(
                {
                    "task_name": POLICY_TEXT_RECORDS_SPEC.task_name,
                    "run_id": run_id,
                    "source_policy_record_id": source_policy.record_id,
                    "item_key": item_key,
                    "failed_at": utc_now_iso(),
                    "error_type": "RuntimeError",
                    "error": error_msg,
                }
            )
        return {
            "source_key": source_key,
            "item_key": item_key,
            "success": False,
            "judge_rejections": outcome.judge_rejections,
            "error": error_msg,
            "policy_decision": source_policy.policy.decision,
            "will_help_now": task.intent_spec.will_help_now,
        }

    record = build_policy_text_record(task, outcome.realization)
    storage.write_item(item_key, record.model_dump())
    logger.info("Realized %s → %s", source_policy.record_id, item_key)
    return {
        "source_key": source_key,
        "item_key": item_key,
        "success": True,
        "judge_rejections": outcome.judge_rejections,
        "error": None,
        "policy_decision": source_policy.policy.decision,
        "will_help_now": task.intent_spec.will_help_now,
    }


def run_generate_policy_records(args: argparse.Namespace) -> None:
    run_dir = POLICY_RECORDS_SPEC.resolve_run_dir(args.run_id, output_dir=args.output_dir)
    storage = DerivedStorageManager(run_dir, POLICY_RECORDS_SPEC.task_name)
    storage.setup()
    existing_keys = set(storage.list_existing_keys())
    if existing_keys and not args.resume:
        print(
            f"Policy run directory already contains {len(existing_keys)} items: {run_dir}\n"
            "Use --resume to continue this run, or choose a new --run-id / --output-dir.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.resume:
        _validate_policy_resume_config(run_dir, args)

    existing_state = storage.load_run_state() if args.resume else None
    decision_weights = {}
    if args.will_help_weight != 1.0:
        decision_weights["engage_now"] = args.will_help_weight
    config_doc = {
        "task": "generate_policy_records",
        "run_id": args.run_id,
        "count_requested": args.count,
        "seed": args.seed,
        "sampler_profile": DEFAULT_PROFILE.name,
        "will_help_weight": args.will_help_weight,
    }
    lineage_doc = {"sources": []}
    result_holder: dict[str, object] = {}

    def execute(context) -> DerivedTaskResult:
        started_at = existing_state.started_at if existing_state and existing_state.started_at else context.created_at
        if args.resume and existing_keys:
            print(f"Resuming — {len(existing_keys)} policy records already exist")

        requested_keys = {make_policy_record_id(i) for i in range(1, args.count + 1)}
        if args.resume and requested_keys.issubset(existing_keys):
            print(f"All {args.count} requested records already exist, nothing to do.")
        else:
            missing_requested = len(requested_keys - existing_keys)
            print(
                f"Generating policy records up to {args.count} total "
                f"(seed={args.seed}, missing={missing_requested}, "
                f"will_help_weight={args.will_help_weight}) ..."
            )
            generator = PolicyGenerator(
                seed=args.seed,
                profile=DEFAULT_PROFILE,
                decision_weights=decision_weights,
            )
            generated_records = generator.generate(count=args.count)
            written_count = _write_policy_records(storage, generated_records, existing_keys)
            logger.info(
                "Materialized %d missing policy records into %s",
                written_count,
                storage.items_dir(),
            )

        all_keys = storage.list_existing_keys()
        export_path = storage.export_path()
        export_lines = _rebuild_policy_records_export_view(storage)
        finished_at = utc_now_iso()
        result_holder.update({
            "all_keys": all_keys,
            "export_path": export_path,
            "export_lines": export_lines,
        })

        return DerivedTaskResult(
            summary={
                "phase": "generation",
                "requested": args.count,
                "generated": len(all_keys),
                "export_lines": export_lines,
                "seed": args.seed,
                "sampler_profile": DEFAULT_PROFILE.name,
                "will_help_weight": args.will_help_weight,
                "generator_version": POLICY_GENERATOR_VERSION,
                "generated_at": finished_at,
            },
            run_state=DerivedRunState(
                total_items=max(args.count, len(all_keys)),
                completed_count=len(all_keys),
                failed_count=0,
                started_at=started_at,
                updated_at=finished_at,
            ),
        )

    def on_error(context, exc: Exception) -> DerivedTaskResult:
        failed_at = utc_now_iso()
        all_keys = storage.list_existing_keys()
        started_at = existing_state.started_at if existing_state and existing_state.started_at else context.created_at
        return DerivedTaskResult(
            status="failed",
            summary={
                "phase": "generation",
                "requested": args.count,
                "generated": len(all_keys),
                "seed": args.seed,
                "sampler_profile": DEFAULT_PROFILE.name,
                "failed_at": failed_at,
                "error": str(exc),
            },
            run_state=DerivedRunState(
                total_items=max(args.count, len(all_keys)),
                completed_count=len(all_keys),
                failed_count=1,
                started_at=started_at,
                updated_at=failed_at,
            ),
        )

    run_derived_task(
        spec=POLICY_RECORDS_SPEC,
        run_id=args.run_id,
        output_dir=args.output_dir,
        language=None,
        config_doc=config_doc,
        lineage_doc=lineage_doc,
        execute=execute,
        on_error=on_error,
    )

    all_keys = result_holder["all_keys"]
    export_path = result_holder["export_path"]
    export_lines = result_holder["export_lines"]

    # --- Per-decision breakdown (read-only, no lock needed post-generation) ---
    decision_counter: dict[str, int] = {}
    for k in all_keys:
        raw = storage.read_item(k)
        if raw is None:
            continue
        decision = raw.get("policy", {}).get("decision", "?")
        decision_counter[decision] = decision_counter.get(decision, 0) + 1
    engage_count = decision_counter.get("engage_now", 0)
    engage_pct = 100 * engage_count / len(all_keys) if all_keys else 0

    print(
        f"Done — {len(all_keys)} policy records in {storage.base}\n"
        f"  export: {export_path} ({export_lines} lines)\n"
        f"  items:  {storage.items_dir()} ({len(all_keys)} files)\n"
        f"  state:  {storage.run_state_path()}"
    )
    print(f"  Decision distribution ({len(all_keys)} total):")
    # Print in canonical order: positive first, then neutral, then negative
    _canonical_decision_order = [
        "engage_now", "engage_briefly",
        "defer", "redirect_channel_or_time",
        "decline", "set_boundary", "minimal_acknowledgment",
    ]
    for d in _canonical_decision_order:
        c = decision_counter.get(d, 0)
        if c:
            pct = 100 * c / len(all_keys)
            will = "✓ will_help" if d == "engage_now" else "✗ won't help"
            bar = "█" * max(1, int(pct))
            print(f"    {d:<28} {c:>5} ({pct:>5.1f}%) {bar} {will}")
    for d in sorted(decision_counter):
        if d not in _canonical_decision_order:
            c = decision_counter[d]
            pct = 100 * c / len(all_keys)
            print(f"    {d:<28} {c:>5} ({pct:>5.1f}%)")
    print(f"    will_help_now=True:  {engage_count}/{len(all_keys)} ({engage_pct:.0f}%)")


def _validate_policy_text_resume_config(run_dir: Path, args: argparse.Namespace) -> None:
    existing_config = load_config_doc(run_dir)
    if existing_config is None:
        return
    if existing_config.get("task") != "generate_policy_text_records":
        print(
            f"Cannot resume non-policy-text run in {run_dir}: "
            f"task={existing_config.get('task')!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    mismatches: list[str] = []
    expected = _policy_text_runtime_config_doc(args)
    for key, expected_value in expected.items():
        actual = existing_config.get(key)
        if actual is not None and actual != expected_value:
            mismatches.append(f"{key}={actual!r} (requested {expected_value!r})")
    if mismatches:
        print(
            f"Resume config mismatch for {run_dir}: " + ", ".join(mismatches),
            file=sys.stderr,
        )
        sys.exit(1)


def _policy_text_runtime_config(args: argparse.Namespace) -> PolicyTextRuntimeConfig:
    return PolicyTextRuntimeConfig(
        model=args.model,
        temperature=args.temperature,
        judge_model=args.judge_model,
    )


def _policy_text_runtime_config_doc(args: argparse.Namespace) -> dict[str, object]:
    runtime = _policy_text_runtime_config(args)
    return {
        "policy_run_id": args.policy_run_id,
        "language": args.language,
        "model": runtime.model,
        "temperature": runtime.temperature,
        "max_records": args.max_records,
        "max_attempts": args.max_attempts,
        "judge_model": runtime.resolved_judge_model,
    }


def run_generate_policy_text_records(args: argparse.Namespace) -> None:
    policy_run = resolve_existing_run(
        task_family=POLICY_TASK_FAMILY,
        run_id=args.policy_run_id,
        run_scope=task_run_scope(POLICY_TASK_FAMILY),
        run_dir=args.policy_run_dir,
    )
    policy_storage = DerivedStorageManager(policy_run.run_dir, POLICY_RECORDS_SPEC.task_name)
    source_keys = policy_storage.list_existing_keys()
    if not source_keys:
        print(f"No source policy records found in {policy_run.run_dir}", file=sys.stderr)
        sys.exit(1)
    if args.max_records is not None:
        source_keys = source_keys[: args.max_records]

    run_dir = POLICY_TEXT_RECORDS_SPEC.resolve_run_dir(
        args.run_id,
        output_dir=args.output_dir,
        language=args.language,
    )
    storage = DerivedStorageManager(run_dir, POLICY_TEXT_RECORDS_SPEC.task_name)
    storage.setup()
    existing_keys = set(storage.list_existing_keys())
    if existing_keys and not args.resume:
        print(
            f"Policy-text run directory already contains {len(existing_keys)} items: {run_dir}\n"
            "Use --resume to continue this run, or choose a new --run-id / --output-dir.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.resume:
        _validate_policy_text_resume_config(run_dir, args)

    existing_state = storage.load_run_state() if args.resume else None
    config_doc = {
        "task": "generate_policy_text_records",
        **_policy_text_runtime_config_doc(args),
    }
    lineage_doc = {
        "sources": [
            {
                "task_family": POLICY_TASK_FAMILY,
                "run_id": args.policy_run_id,
                "path": str(policy_run.run_dir),
                "use": "policy_text_source",
                "artifact_ref": make_artifact_ref(POLICY_TASK_FAMILY, args.policy_run_id, "artifact", "items"),
            }
        ]
    }
    result_holder: dict[str, object] = {}
    requested_item_keys = {
        make_policy_text_record_id(source_key)
        for source_key in source_keys
    }
    runtime_config = _policy_text_runtime_config(args)

    def execute(context) -> DerivedTaskResult:
        started_at = existing_state.started_at if existing_state and existing_state.started_at else context.created_at
        failed_items = storage.count_failure_events() if args.resume else 0
        judge_rejections = 0
        if args.resume and existing_keys:
            print(f"Resuming — {len(existing_keys)} policy-text records already exist")
            validated = _validate_existing_policy_text_records(storage)
            _validate_policy_text_records_against_source(storage, policy_storage)
            print(f"Validated {validated} existing policy-text records against their source policies; rebuilding export view ...")
            _rebuild_policy_text_export_view(storage)
        if args.resume and requested_item_keys.issubset(existing_keys):
            print(f"All {len(requested_item_keys)} requested policy-text records already exist, nothing to do.")
        else:
            base_url, api_key = get_llm_env()
            pending_keys = [k for k in source_keys if make_policy_text_record_id(k) not in existing_keys]
            total_pending = len(pending_keys)
            if not pending_keys:
                print("All requested policy-text records already exist, nothing to do.")
            else:
                max_workers = max(1, args.max_workers)
                logger.info(
                    "Policy-text generation runtime: generator_model=%s judge_model=%s max_attempts=%s max_workers=%s",
                    runtime_config.model,
                    runtime_config.resolved_judge_model,
                    args.max_attempts,
                    max_workers,
                )
                print(
                    f"Realizing {total_pending} policy-text records "
                    f"with {max_workers} worker(s) ..."
                )
                failure_lock = threading.Lock()
                completed_count = 0
                # Per-worker stats: each worker returns its own decision info,
                # controller aggregates without contention.
                decision_counter: dict[str, int] = {}
                will_help_counter: dict[str, int] = {"true": 0, "false": 0}
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {
                        executor.submit(
                            _realize_one_policy_text,
                            source_key,
                            policy_storage=policy_storage,
                            storage=storage,
                            base_url=base_url,
                            api_key=api_key,
                            language=args.language,
                            runtime_config=runtime_config,
                            max_attempts=args.max_attempts,
                            run_id=args.run_id,
                            failure_lock=failure_lock,
                        ): source_key
                        for source_key in pending_keys
                    }
                    for future in as_completed(futures):
                        source_key = futures[future]
                        try:
                            worker_outcome = future.result()
                        except Exception as exc:
                            failed_items += 1
                            item_key = make_policy_text_record_id(source_key)
                            with failure_lock:
                                storage.append_failure(
                                    {
                                        "task_name": POLICY_TEXT_RECORDS_SPEC.task_name,
                                        "run_id": args.run_id,
                                        "source_policy_record_id": source_key,
                                        "item_key": item_key,
                                        "failed_at": utc_now_iso(),
                                        "error_type": type(exc).__name__,
                                        "error": str(exc),
                                    }
                                )
                            logger.warning(
                                "Unhandled worker failure for %s: %s",
                                source_key,
                                exc,
                            )
                        else:
                            judge_rejections += worker_outcome.get("judge_rejections", 0)
                            # Per-worker diagnostic stats — no lock needed
                            dec = worker_outcome.get("policy_decision", "?")
                            decision_counter[dec] = decision_counter.get(dec, 0) + 1
                            wh = worker_outcome.get("will_help_now", None)
                            if wh is True:
                                will_help_counter["true"] += 1
                            elif wh is False:
                                will_help_counter["false"] += 1
                            if not worker_outcome.get("success"):
                                failed_items += 1
                            completed_count += 1
                            if completed_count % 10 == 0 or completed_count == total_pending:
                                print(
                                    f"  Progress: {completed_count}/{total_pending} "
                                    f"({failed_items} failed)"
                                )

        all_keys = storage.list_existing_keys()
        generated_requested = len(requested_item_keys.intersection(all_keys))
        export_path = storage.export_path()
        export_lines = _rebuild_policy_text_export_view(storage)
        finished_at = utc_now_iso()
        result_holder.update({
            "all_keys": all_keys,
            "export_path": export_path,
            "export_lines": export_lines,
            "source_total": len(source_keys),
            "decision_counter": decision_counter,
            "will_help_counter": will_help_counter,
        })
        return DerivedTaskResult(
            summary={
                "phase": "text_realization",
                "source_policy_run_id": args.policy_run_id,
                "language": args.language,
                "requested": len(source_keys),
                "generated": generated_requested,
                "failed_items": failed_items,
                "export_lines": export_lines,
                "model": runtime_config.model,
                "temperature": runtime_config.temperature,
                "judge_model": runtime_config.resolved_judge_model,
                "judge_rejections": judge_rejections,
                "max_attempts": args.max_attempts,
                "generated_at": finished_at,
                "will_help_now_distribution": dict(will_help_counter),
                "decision_distribution": dict(decision_counter),
            },
            run_state=DerivedRunState(
                total_items=len(source_keys),
                completed_count=generated_requested,
                failed_count=failed_items,
                started_at=started_at,
                updated_at=finished_at,
            ),
            status="completed_with_failures" if failed_items else "completed",
        )

    def on_error(context, exc: Exception) -> DerivedTaskResult:
        failed_at = utc_now_iso()
        all_keys = storage.list_existing_keys()
        generated_requested = len(requested_item_keys.intersection(all_keys))
        failure_events = storage.count_failure_events()
        started_at = existing_state.started_at if existing_state and existing_state.started_at else context.created_at
        return DerivedTaskResult(
            status="failed",
            summary={
                "phase": "text_realization",
                "source_policy_run_id": args.policy_run_id,
                "language": args.language,
                "requested": len(source_keys),
                "generated": generated_requested,
                "model": runtime_config.model,
                "judge_model": runtime_config.resolved_judge_model,
                "max_attempts": args.max_attempts,
                "failed_at": failed_at,
                "error": str(exc),
            },
            run_state=DerivedRunState(
                total_items=len(source_keys),
                completed_count=generated_requested,
                failed_count=failure_events if failure_events else 1,
                started_at=started_at,
                updated_at=failed_at,
            ),
        )

    run_derived_task(
        spec=POLICY_TEXT_RECORDS_SPEC,
        run_id=args.run_id,
        output_dir=args.output_dir,
        language=args.language,
        config_doc=config_doc,
        lineage_doc=lineage_doc,
        execute=execute,
        on_error=on_error,
    )

    all_keys = result_holder["all_keys"]
    export_path = result_holder["export_path"]
    export_lines = result_holder["export_lines"]
    decision_counter: dict[str, int] = result_holder.get("decision_counter", {})
    will_help_counter: dict[str, int] = result_holder.get("will_help_counter", {})
    total_processed = sum(decision_counter.values())
    print(
        f"Done — {len(all_keys)} policy text records in {storage.base}\n"
        f"  export: {export_path} ({export_lines} lines)\n"
        f"  items:  {storage.items_dir()} ({len(all_keys)} files)\n"
        f"  state:  {storage.run_state_path()}"
    )
    if total_processed:
        print(f"  Decision distribution ({total_processed} processed):")
        _canonical_decision_order = [
            "engage_now", "engage_briefly",
            "defer", "redirect_channel_or_time",
            "decline", "set_boundary", "minimal_acknowledgment",
        ]
        for d in _canonical_decision_order:
            c = decision_counter.get(d, 0)
            if c:
                pct = 100 * c / total_processed
                will = "✓ will_help" if d == "engage_now" else "✗ won't help"
                bar = "█" * max(1, int(pct))
                print(f"    {d:<28} {c:>5} ({pct:>5.1f}%) {bar} {will}")
        wht = will_help_counter.get("true", 0)
        whf = will_help_counter.get("false", 0)
        print(f"    will_help_now=True:  {wht}/{total_processed} ({100*wht/total_processed:.0f}%)")
        print(f"    will_help_now=False: {whf}/{total_processed} ({100*whf/total_processed:.0f}%)")
