#!/usr/bin/env python3
"""Shared implementation for derived-data task mains."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from contextlib import closing
from pathlib import Path

from api import LLMClient
from derived_lifecycle import DerivedTaskResult, run_derived_task
from derived_specs import POLICY_RECORDS_SPEC, POLICY_TEXT_RECORDS_SPEC
from derived_storage import DerivedRunState, DerivedStorageManager
from fs_utils import write_jsonl
from policy_generator import DEFAULT_PROFILE, PolicyGenerator
from policy_models import PolicyRecord, make_policy_record_id
from policy_text_generator import PolicyTextGenerator, select_text_profile
from policy_text_models import (
    PolicyTextArtifactRecord,
    TEXT_SCHEMA_VERSION,
    intent_spec_from_decision,
    make_policy_text_record_id,
    project_policy_text_export,
    validate_policy_text_artifact,
)
from relation_catalog import canonical_relation_kind
from run_metadata import load_config_doc, utc_now_iso
from run_paths import resolve_task_run_input
from run_resolver import resolve_existing_run
from task_contracts import (
    POLICY_TASK_FAMILY,
    POLICY_TEXT_TASK_FAMILY,
    make_artifact_ref,
    task_run_scope,
)

logger = logging.getLogger(__name__)


def _load_validated_policy_text_artifacts(storage: DerivedStorageManager) -> list[PolicyTextArtifactRecord]:
    artifacts: list[PolicyTextArtifactRecord] = []
    errors: list[str] = []
    for item_key in storage.list_existing_keys():
        raw = storage.read_item(item_key)
        if raw is None:
            errors.append(f"{item_key}: missing artifact payload")
            continue
        try:
            artifacts.append(validate_policy_text_artifact(raw, expected_item_key=item_key))
        except Exception as exc:
            errors.append(f"{item_key}: {exc}")
    if errors:
        preview = "; ".join(errors[:3])
        extra = "" if len(errors) <= 3 else f" (+{len(errors) - 3} more)"
        raise ValueError(f"Policy-text artifact contract violations: {preview}{extra}")
    return artifacts


def _rebuild_policy_text_export_view(storage: DerivedStorageManager) -> int:
    export_records = [
        project_policy_text_export(artifact).model_dump()
        for artifact in _load_validated_policy_text_artifacts(storage)
    ]
    write_jsonl(storage.export_path(), export_records)
    return len(export_records)


def _validate_existing_policy_text_artifacts(storage: DerivedStorageManager) -> int:
    try:
        return len(_load_validated_policy_text_artifacts(storage))
    except ValueError as exc:
        raise ValueError(
            str(exc).replace(
                "Policy-text artifact contract violations",
                "Existing policy-text artifacts failed validation",
            )
        ) from exc


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
        "--seed",
        type=int,
        default=7,
        help="Seed used for deterministic style-profile assignment.",
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
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging",
    )
    return parser


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
    config_doc = {
        "task": "generate_policy_records",
        "run_id": args.run_id,
        "count_requested": args.count,
        "seed": args.seed,
        "sampler_profile": DEFAULT_PROFILE.name,
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
                f"(seed={args.seed}, missing={missing_requested}) ..."
            )
            generator = PolicyGenerator(seed=args.seed, profile=DEFAULT_PROFILE)
            generated_records = generator.generate(count=args.count)
            written_count = _write_policy_records(storage, generated_records, existing_keys)
            logger.info(
                "Materialized %d missing policy records into %s",
                written_count,
                storage.items_dir(),
            )

        all_keys = storage.list_existing_keys()
        export_path = storage.export_path()
        export_lines = storage.rebuild_export_view()
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
                "generator_version": "1.0",
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
    print(
        f"Done — {len(all_keys)} policy records in {storage.base}\n"
        f"  export: {export_path} ({export_lines} lines)\n"
        f"  items:  {storage.items_dir()} ({len(all_keys)} files)\n"
        f"  state:  {storage.run_state_path()}"
    )


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
    expected = {
        "policy_run_id": args.policy_run_id,
        "language": args.language,
        "model": args.model,
        "temperature": args.temperature,
        "seed": args.seed,
        "max_records": args.max_records,
    }
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
        "policy_run_id": args.policy_run_id,
        "language": args.language,
        "model": args.model,
        "temperature": args.temperature,
        "seed": args.seed,
        "max_records": args.max_records,
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

    def execute(context) -> DerivedTaskResult:
        started_at = existing_state.started_at if existing_state and existing_state.started_at else context.created_at
        failed_items = storage.count_failure_events() if args.resume else 0
        if args.resume and existing_keys:
            print(f"Resuming — {len(existing_keys)} policy-text records already exist")
            validated = _validate_existing_policy_text_artifacts(storage)
            print(f"Validated {validated} existing policy-text artifacts; rebuilding export view ...")
            _rebuild_policy_text_export_view(storage)
        if args.resume and requested_item_keys.issubset(existing_keys):
            print(f"All {len(requested_item_keys)} requested policy-text records already exist, nothing to do.")
        else:
            base_url, api_key = get_llm_env()
            with closing(LLMClient(base_url=base_url, api_key=api_key, model=args.model)) as llm:
                generator = PolicyTextGenerator(
                    llm,
                    language=args.language,
                    temperature=args.temperature,
                )
                for index, source_key in enumerate(source_keys, start=1):
                    item_key = make_policy_text_record_id(source_key)
                    if item_key in existing_keys:
                        continue
                    raw = policy_storage.read_item(source_key)
                    if raw is None:
                        raise FileNotFoundError(f"Missing source policy record: {source_key}")
                    source_policy = PolicyRecord(**raw)
                    if source_policy.record_id != source_key:
                        raise ValueError(
                            f"Source policy record_id {source_policy.record_id!r} does not match item key {source_key!r}"
                        )
                    intent_spec = intent_spec_from_decision(source_policy.policy.decision)
                    relation_kind = canonical_relation_kind(source_policy.relation.relation_label)
                    text_profile = select_text_profile(source_policy.record_id, args.seed)
                    last_error: Exception | None = None
                    realization = None
                    for attempt in range(1, args.max_attempts + 1):
                        logger.info(
                            "Realizing %s (%d/%d, attempt=%d/%d, will_help_now=%s, response_intent=%s, profile=%s)",
                            source_policy.record_id,
                            index,
                            len(source_keys),
                            attempt,
                            args.max_attempts,
                            intent_spec.will_help_now,
                            intent_spec.response_intent,
                            text_profile,
                        )
                        try:
                            realization = generator.generate(
                                source_policy,
                                intent_spec=intent_spec,
                                text_profile=text_profile,
                            )
                            last_error = None
                            break
                        except Exception as exc:
                            last_error = exc
                            logger.warning(
                                "Policy text realization failed for %s on attempt %d/%d: %s",
                                source_policy.record_id,
                                attempt,
                                args.max_attempts,
                                exc,
                            )
                    if last_error is not None:
                        failed_items += 1
                        storage.append_failure(
                            {
                                "task_name": POLICY_TEXT_RECORDS_SPEC.task_name,
                                "run_id": args.run_id,
                                "source_policy_record_id": source_policy.record_id,
                                "item_key": item_key,
                                "failed_at": utc_now_iso(),
                                "error_type": type(last_error).__name__,
                                "error": str(last_error),
                            }
                        )
                        continue

                    if realization is None:
                        raise RuntimeError(
                            f"Policy text realization unexpectedly missing for {source_policy.record_id}"
                        )
                    record = validate_policy_text_artifact(
                        PolicyTextArtifactRecord(
                            schema_version=TEXT_SCHEMA_VERSION,
                            record_id=item_key,
                            language=args.language,
                            source_policy_record_id=source_policy.record_id,
                            relation_kind=relation_kind,
                            will_help_now=intent_spec.will_help_now,
                            policy_decision=source_policy.policy.decision,
                            response_intent=intent_spec.response_intent,
                            text_profile=text_profile,
                            belief=realization.belief.strip(),
                            thinking=realization.thinking.strip(),
                            source_policy=source_policy,
                        ),
                        expected_item_key=item_key,
                    )
                    storage.write_item(item_key, record.model_dump())

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
                "model": args.model,
                "temperature": args.temperature,
                "seed": args.seed,
                "generated_at": finished_at,
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
                "model": args.model,
                "seed": args.seed,
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
    print(
        f"Done — {len(all_keys)} policy text records in {storage.base}\n"
        f"  export: {export_path} ({export_lines} lines)\n"
        f"  items:  {storage.items_dir()} ({len(all_keys)} files)\n"
        f"  state:  {storage.run_state_path()}"
    )
