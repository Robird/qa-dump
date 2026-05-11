#!/usr/bin/env python3
"""Shared implementation for derived-data task mains."""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from pathlib import Path

from derived_lifecycle import DerivedTaskResult, run_derived_task
from derived_specs import HELP_GATE_PREFLIGHT_SPEC, POLICY_RECORDS_SPEC
from derived_storage import DerivedRunState, DerivedStorageManager
from payload_adapter import QAPayloadAdapter
from policy_generator import DEFAULT_PROFILE, PolicyGenerator
from policy_models import make_policy_record_id
from qa_view import QAViewReader
from run_metadata import load_config_doc, utc_now_iso
from run_paths import resolve_task_run_input
from run_resolver import resolve_existing_run
from task_contracts import (
    HELP_GATE_TASK_FAMILY,
    POLICY_TASK_FAMILY,
    QA_TASK_FAMILY,
    QA_VIEW_ID,
    make_artifact_ref,
    task_run_scope,
)

logger = logging.getLogger(__name__)


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


def default_qa_run_dir(language: str, run_id: str) -> Path:
    return resolve_task_run_input(QA_TASK_FAMILY, run_id, language=language)


def default_policy_run_dir(run_id: str) -> Path:
    return resolve_task_run_input(POLICY_TASK_FAMILY, run_id)


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


def add_help_gate_preflight_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--run-id",
        required=True,
        help="Current help-gate run id.",
    )
    parser.add_argument(
        "--qa-run-id",
        required=True,
        help="Source QA run id.",
    )
    parser.add_argument(
        "--policy-run-id",
        required=True,
        help="Source policy-record run id.",
    )
    parser.add_argument(
        "--qa-run-dir",
        default=None,
        help="Explicit source QA run directory (overrides --language/--qa-run-id lookup)",
    )
    parser.add_argument(
        "--policy-run-dir",
        default=None,
        help="Explicit source policy-record run directory (overrides --policy-run-id lookup)",
    )
    parser.add_argument(
        "--domains",
        nargs="*",
        default=None,
        help="Limit to specific QA export domain slugs",
    )
    parser.add_argument(
        "--bloom-levels",
        nargs="*",
        default=None,
        help="Limit to specific bloom levels",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=None,
        help="Maximum payload records to load (for preflight sampling)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Explicit output directory for the current help-gate run",
    )
    parser.add_argument(
        "--language",
        default="zh",
        choices=["zh", "en"],
        help="Language scope for the help-gate run and QA lookup",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reserved flag for future resumable help-gate tasks",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging",
    )


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
        "resume": args.resume,
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
                task_name=POLICY_RECORDS_SPEC.task_name,
                run_id=args.run_id,
                total_items=max(args.count, len(all_keys)),
                completed_count=len(all_keys),
                failed_count=0,
                started_at=started_at,
                updated_at=finished_at,
                last_cursor=all_keys[-1] if all_keys else "",
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
                task_name=POLICY_RECORDS_SPEC.task_name,
                run_id=args.run_id,
                total_items=max(args.count, len(all_keys)),
                completed_count=len(all_keys),
                failed_count=1,
                started_at=started_at,
                updated_at=failed_at,
                last_cursor=all_keys[-1] if all_keys else "",
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


def run_help_gate_preflight(args: argparse.Namespace) -> None:
    try:
        qa_run = resolve_existing_run(
            task_family=QA_TASK_FAMILY,
            run_id=args.qa_run_id,
            language=args.language,
            run_scope=task_run_scope(QA_TASK_FAMILY),
            run_dir=args.qa_run_dir,
        )
        QAViewReader.from_input(qa_run.run_dir)
    except (FileNotFoundError, ValueError) as exc:
        qa_run_dir = Path(args.qa_run_dir) if args.qa_run_dir else default_qa_run_dir(args.language, args.qa_run_id)
        print(f"Invalid QA run directory {qa_run_dir}: {exc}", file=sys.stderr)
        sys.exit(1)
    qa_run_dir = qa_run.run_dir

    try:
        policy_run = resolve_existing_run(
            task_family=POLICY_TASK_FAMILY,
            run_id=args.policy_run_id,
            run_scope=task_run_scope(POLICY_TASK_FAMILY),
            run_dir=args.policy_run_dir,
        )
    except (FileNotFoundError, ValueError) as exc:
        policy_run_dir = Path(args.policy_run_dir) if args.policy_run_dir else default_policy_run_dir(args.policy_run_id)
        print(f"Invalid policy run directory {policy_run_dir}: {exc}", file=sys.stderr)
        print(
            "Generate policy records first, for example:\n"
            f"  python policy_records_main.py --run-id {args.policy_run_id}"
            + (f" --output-dir {args.policy_run_dir}" if args.policy_run_dir else ""),
            file=sys.stderr,
        )
        sys.exit(1)
    policy_run_dir = policy_run.run_dir

    config_doc = {
        "task": "help_gate_preflight",
        "resume": args.resume,
    }
    lineage_doc = {
        "sources": [
            {
                "task_family": QA_TASK_FAMILY,
                "run_id": args.qa_run_id,
                "path": str(qa_run_dir),
                "use": "payload_adapter",
                "artifact_ref": make_artifact_ref(QA_TASK_FAMILY, args.qa_run_id, "view", QA_VIEW_ID),
                "filters": {
                    "domains": args.domains,
                    "bloom_levels": args.bloom_levels,
                    "max_records": args.max_records,
                },
            },
            {
                "task_family": POLICY_RECORDS_SPEC.task_family,
                "run_id": args.policy_run_id,
                "path": str(policy_run_dir),
                "use": "policy_source",
                "artifact_ref": make_artifact_ref(POLICY_RECORDS_SPEC.task_family, args.policy_run_id, "artifact", "items"),
            },
        ]
    }
    result_holder: dict[str, object] = {}

    def execute(context) -> DerivedTaskResult:
        started_at = context.created_at
        print(f"Loading payloads from {qa_run_dir / 'views' / QA_VIEW_ID} ...")
        adapter = QAPayloadAdapter(str(qa_run_dir))

        bloom_filter = set(args.bloom_levels) if args.bloom_levels else None
        domain_slugs = args.domains

        if domain_slugs:
            all_payloads: list = []
            for slug in domain_slugs:
                remaining = None
                if args.max_records is not None:
                    remaining = max(0, args.max_records - len(all_payloads))
                    if remaining == 0:
                        break
                all_payloads.extend(
                    adapter.discover(domain_slug=slug, bloom_filter=bloom_filter, max_records=remaining)
                )
        else:
            all_payloads = adapter.discover(bloom_filter=bloom_filter, max_records=args.max_records)

        print(f"  Loaded {len(all_payloads)} payload records")

        policy_storage = DerivedStorageManager(policy_run_dir, POLICY_RECORDS_SPEC.task_name)
        policy_keys = policy_storage.list_existing_keys()
        policy_count = len(policy_keys)
        if policy_count == 0:
            print(
                "  No policy records found. Run 'generate_policy_records' first:\n"
                f"    python policy_records_main.py --run-id {args.policy_run_id}"
                + (f" --output-dir {args.policy_run_dir}" if args.policy_run_dir else ""),
                file=sys.stderr,
            )

        print(f"  Found {policy_count} policy records")

        domain_counts = Counter(p.domain_slug for p in all_payloads)
        bloom_counts = Counter(p.bloom_level for p in all_payloads)
        sample_payloads = all_payloads[:5]
        sample_policies = []
        for key in policy_keys[:3]:
            data = policy_storage.read_item(key)
            if data:
                sample_policies.append(data)

        total_pairs = len(all_payloads) * policy_count if policy_count > 0 else 0
        finished_at = utc_now_iso()
        preflight = {
            "task_family": HELP_GATE_PREFLIGHT_SPEC.task_family,
            "run_scope": task_run_scope(HELP_GATE_TASK_FAMILY),
            "phase": "preflight",
            "run_id": args.run_id,
            "qa_run_id": args.qa_run_id,
            "policy_run_id": args.policy_run_id,
            "generated_at": finished_at,
            "payloads": {
                "total": len(all_payloads),
                "domain_distribution": dict(domain_counts.most_common()),
                "bloom_distribution": dict(bloom_counts.most_common()),
                "sample": [
                    {
                        "payload_id": p.payload_id,
                        "domain_slug": p.domain_slug,
                        "bloom_level": p.bloom_level,
                        "request_preview": p.request_text[:80],
                    }
                    for p in sample_payloads
                ],
            },
            "policy_records": {
                "total": policy_count,
                "sample": sample_policies[:3],
            },
            "composition": {
                "estimated_pairs": total_pairs,
                "status": "ready" if policy_count > 0 and len(all_payloads) > 0 else "blocked",
                "warnings": _compute_preflight_warnings(all_payloads, policy_count),
            },
        }

        preflight_path = context.storage.write_json("artifacts/preflight/composition_preflight.json", preflight)
        result_holder.update({
            "preflight_path": preflight_path,
            "payload_count": len(all_payloads),
            "domain_count": len(domain_counts),
            "policy_count": policy_count,
            "total_pairs": total_pairs,
            "status": preflight["composition"]["status"],
            "warnings": preflight["composition"]["warnings"],
        })
        return DerivedTaskResult(
            summary={
                "phase": "preflight",
                "qa_run_id": args.qa_run_id,
                "policy_run_id": args.policy_run_id,
                "payload_count": len(all_payloads),
                "policy_count": policy_count,
                "estimated_pairs": total_pairs,
                "preflight_status": preflight["composition"]["status"],
                "warnings": preflight["composition"]["warnings"],
                "generated_at": finished_at,
            },
            run_state=DerivedRunState(
                task_name=HELP_GATE_PREFLIGHT_SPEC.task_name,
                run_id=args.run_id,
                total_items=1,
                completed_count=1,
                failed_count=0,
                started_at=started_at,
                updated_at=finished_at,
                last_cursor="preflight",
            ),
        )

    def on_error(context, exc: Exception) -> DerivedTaskResult:
        failed_at = utc_now_iso()
        return DerivedTaskResult(
            status="failed",
            summary={
                "phase": "preflight",
                "qa_run_id": args.qa_run_id,
                "policy_run_id": args.policy_run_id,
                "failed_at": failed_at,
                "error": str(exc),
            },
            run_state=DerivedRunState(
                task_name=HELP_GATE_PREFLIGHT_SPEC.task_name,
                run_id=args.run_id,
                total_items=1,
                completed_count=0,
                failed_count=1,
                started_at=context.created_at,
                updated_at=failed_at,
                last_cursor="",
            ),
        )

    run_derived_task(
        spec=HELP_GATE_PREFLIGHT_SPEC,
        run_id=args.run_id,
        output_dir=args.output_dir,
        language=args.language,
        config_doc=config_doc,
        lineage_doc=lineage_doc,
        execute=execute,
        on_error=on_error,
    )

    print(f"\nComposition preflight written to {result_holder['preflight_path']}")
    print(f"  Payloads:   {result_holder['payload_count']} ({result_holder['domain_count']} domains)")
    print(f"  Policies:   {result_holder['policy_count']}")
    print(f"  Est. pairs: {result_holder['total_pairs']:,}")
    print(f"  Status:     {result_holder['status']}")
    for warning in result_holder["warnings"]:
        print(f"  Warning:    {warning}")


def _compute_preflight_warnings(payloads: list, policy_count: int) -> list[str]:
    warnings: list[str] = []
    if not payloads:
        warnings.append("No payload records found — check the QA export view.")
    if policy_count == 0:
        warnings.append("No policy records found — run generate_policy_records first.")
    if policy_count > 0 and len(payloads) > 0:
        blooms = {p.bloom_level for p in payloads if p.bloom_level}
        if len(blooms) < 3:
            warnings.append(f"Only {len(blooms)} bloom levels represented across payloads.")
    return warnings
