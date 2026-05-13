"""Help-gate ACML CLI and orchestration."""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from derived_lifecycle import DerivedTaskResult, run_derived_task
from derived_specs import HELP_GATE_ACML_SPEC
from derived_storage import DerivedRunState, DerivedStorageManager
from fs_utils import atomic_write_text
from help_gate_acml import (
    HELP_GATE_ACML_COMPOSITION_VERSION,
    build_acml_composition,
    build_acml_document,
    make_sample_id,
    render_acml_document,
    validate_acml_sample,
)
from help_gate_source_plan import (
    HelpGateSourcePlan,
    HelpGateSourcePlanError,
    HelpGateSourceRequest,
    resolve_help_gate_source_plan,
)
from policy_text_contracts import LANGUAGE_VALUES, PolicyDecisionName, RelationKind, ResponseIntent
from run_metadata import load_config_doc, utc_now_iso
from task_contracts import HELP_GATE_TASK_FAMILY, QA_VIEW_ID, task_run_scope

logger = logging.getLogger(__name__)


class HelpGateACMLItem(BaseModel):
    sample_id: str
    qa_record_id: str
    policy_text_record_id: str
    relation_kind: RelationKind
    will_help_now: bool
    response_intent: ResponseIntent
    composition_version: str
    source_counterparty_entity_id: str
    sample_counterparty_entity_id: str
    counterparty_canonical_name: str
    counterparty_first_mention_name: str
    reply_tool_name: str
    belief_runtime_affordance_variant_id: str
    policy_decision: PolicyDecisionName
    domain_slug: str
    bloom_level: str
    created_at: str


@dataclass(frozen=True)
class HelpGateGenerationOutcome:
    generated: int
    failed_items: int
    skipped_existing: int
    all_items: tuple[HelpGateACMLItem, ...]


def add_help_gate_acml_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--run-id",
        required=True,
        help="Current help-gate ACML run id.",
    )
    _add_help_gate_source_arguments(parser)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Explicit output directory for the help-gate ACML run",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume by skipping already-completed samples",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Write the preflight report and stop before ACML generation",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging",
    )


def _add_help_gate_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--qa-run-id",
        required=True,
        help="Source QA run id.",
    )
    parser.add_argument(
        "--policy-text-run-id",
        required=True,
        help="Source policy-text run id.",
    )
    parser.add_argument(
        "--qa-run-dir",
        default=None,
        help="Explicit source QA run directory (overrides --language/--qa-run-id lookup)",
    )
    parser.add_argument(
        "--policy-text-run-dir",
        default=None,
        help="Explicit source policy-text run directory (overrides --language/--policy-text-run-id lookup)",
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
        "--max-samples",
        type=int,
        default=None,
        help="Maximum ACML samples after source-side filters",
    )
    parser.add_argument(
        "--language",
        default="zh",
        choices=list(LANGUAGE_VALUES),
        help="Language scope for the help-gate run and source lookups",
    )


def _help_gate_request_from_args(args: argparse.Namespace) -> HelpGateSourceRequest:
    return HelpGateSourceRequest(
        language=args.language,
        qa_run_id=args.qa_run_id,
        policy_text_run_id=args.policy_text_run_id,
        qa_run_dir=args.qa_run_dir,
        policy_text_run_dir=args.policy_text_run_dir,
        domains=tuple(args.domains or ()),
        bloom_levels=tuple(args.bloom_levels or ()),
        max_samples=args.max_samples,
    )


def _help_gate_summary_source_fields(plan: HelpGateSourcePlan) -> dict:
    return plan.summary_source_fields()


def _help_gate_config_doc(
    *,
    request: HelpGateSourceRequest,
) -> dict:
    return {
        "task": "help_gate_acml",
        "composition_version": HELP_GATE_ACML_COMPOSITION_VERSION,
        **request.config_fields(),
    }


def _validate_help_gate_acml_resume_config(run_dir: Path, *, request: HelpGateSourceRequest) -> None:
    existing_config = load_config_doc(run_dir)
    if existing_config is None:
        return
    if existing_config.get("task") != "help_gate_acml":
        print(
            f"Cannot resume non-help-gate ACML run in {run_dir}: task={existing_config.get('task')!r}",
            file=sys.stderr,
        )
        sys.exit(1)
    expected = request.config_fields()
    expected = {
        "composition_version": HELP_GATE_ACML_COMPOSITION_VERSION,
        **expected,
    }
    mismatches = [
        f"{key}={existing_config.get(key)!r} (requested {value!r})"
        for key, value in expected.items()
        if existing_config.get(key) != value
    ]
    if mismatches:
        print(f"Resume config mismatch for {run_dir}: " + ", ".join(mismatches), file=sys.stderr)
        sys.exit(1)


def _help_gate_acml_has_existing_state(run_dir: Path) -> bool:
    return load_config_doc(run_dir) is not None


def _build_help_gate_preflight_report(
    *,
    run_id: str,
    plan: HelpGateSourcePlan,
    generated_at: str,
) -> dict:
    return {
        "task_family": HELP_GATE_TASK_FAMILY,
        "run_scope": task_run_scope(HELP_GATE_TASK_FAMILY),
        "phase": "preflight",
        "run_id": run_id,
        "qa_run_id": plan.request.qa_run_id,
        "qa_view_id": plan.qa_view_id,
        "qa_export_schema_version": plan.qa_export_schema_version,
        "policy_text_run_id": plan.request.policy_text_run_id,
        "policy_text_export_schema_version": plan.policy_text_export_schema_version,
        "generated_at": generated_at,
        "payloads": {
            "total": plan.payload_count,
            "domain_distribution": plan.payload_domain_distribution(),
            "bloom_distribution": plan.payload_bloom_distribution(),
            "sample": [
                {
                    "payload_id": payload.payload_id,
                    "domain_slug": payload.domain_slug,
                    "bloom_level": payload.bloom_level,
                    "request_preview": payload.request_text[:80],
                }
                for payload in plan.sample_payloads()
            ],
        },
        "policy_text_records": {
            "total": plan.policy_text_count,
            "will_help_now_distribution": plan.policy_text_will_help_distribution(),
            "response_intent_distribution": plan.policy_text_intent_distribution(),
            "sample": [record.model_dump() for record in plan.sample_policy_text_records()],
        },
        "composition": {
            "composition_version": HELP_GATE_ACML_COMPOSITION_VERSION,
            "pairing_strategy": plan.pairing_strategy,
            "estimated_samples": plan.estimated_samples,
            "generation_readiness": plan.generation_readiness,
            "warnings": plan.warnings(),
        },
    }


def _run_preflight(
    *,
    context,
    run_id: str,
    plan: HelpGateSourcePlan,
) -> None:
    preflight = _build_help_gate_preflight_report(
        run_id=run_id,
        plan=plan,
        generated_at=utc_now_iso(),
    )
    context.storage.write_json("artifacts/preflight/composition_preflight.json", preflight)


def _load_all_help_gate_items(storage: DerivedStorageManager) -> tuple[HelpGateACMLItem, ...]:
    return tuple(HelpGateACMLItem(**raw) for raw in storage.iter_items())


def _list_existing_acml_sample_ids(run_dir: Path) -> set[str]:
    """Scan artifacts/samples/**/*.acml and extract sample IDs from filenames."""
    samples_dir = run_dir / "artifacts" / "samples"
    if not samples_dir.is_dir():
        return set()
    ids: set[str] = set()
    for acml_path in samples_dir.rglob("*.acml"):
        ids.add(acml_path.stem)
    return ids


def _generate_samples(
    *,
    context,
    storage: DerivedStorageManager,
    plan: HelpGateSourcePlan,
    existing_keys: set[str],
) -> HelpGateGenerationOutcome:
    failed_items = 0
    skipped_existing = 0
    completed_keys = set(existing_keys)
    collected_items: list[HelpGateACMLItem] = []
    request = plan.request
    for pairing in plan.iter_pairs():
        sample_id = make_sample_id(
            qa_run_id=request.qa_run_id,
            qa_view_id=QA_VIEW_ID,
            qa_record_id=pairing.payload.payload_id,
            policy_text_run_id=request.policy_text_run_id,
            policy_text_record_id=pairing.policy_text.record_id,
            language=request.language,
        )
        if sample_id in completed_keys:
            skipped_existing += 1
            continue
        logger.info(
            "Composing ACML %s (%d/%d, qa=%s, policy_text=%s, will_help_now=%s)",
            sample_id,
            pairing.index,
            plan.estimated_samples,
            pairing.payload.payload_id,
            pairing.policy_text.record_id,
            pairing.policy_text.will_help_now,
        )
        try:
            composition = build_acml_composition(
                sample_id=sample_id,
                language=request.language,
                payload=pairing.payload,
                policy_text=pairing.policy_text,
            )
            document = build_acml_document(composition=composition)
            rendered = render_acml_document(document)
            issues = validate_acml_sample(
                composition=composition,
                document=rendered.parsed_document,
            )
            if issues:
                raise ValueError("; ".join(issues))
            bloom_dir = pairing.payload.bloom_level or "_unlabeled"
            sample_path = context.run_dir / "artifacts" / "samples" / bloom_dir / f"{sample_id}.acml"
            atomic_write_text(sample_path, rendered.text)
            item = HelpGateACMLItem(
                sample_id=sample_id,
                qa_record_id=pairing.payload.payload_id,
                policy_text_record_id=pairing.policy_text.record_id,
                relation_kind=pairing.policy_text.relation_kind,
                will_help_now=pairing.policy_text.will_help_now,
                response_intent=pairing.policy_text.response_intent,
                policy_decision=pairing.policy_text.policy_decision,
                domain_slug=pairing.payload.domain_slug,
                bloom_level=pairing.payload.bloom_level,
                created_at=utc_now_iso(),
                composition_version=HELP_GATE_ACML_COMPOSITION_VERSION,
                source_counterparty_entity_id=composition.source_counterparty_entity_id,
                sample_counterparty_entity_id=composition.sample_counterparty_entity_id,
                counterparty_canonical_name=composition.counterparty_canonical_name,
                counterparty_first_mention_name=composition.counterparty_first_mention_name,
                reply_tool_name=composition.reply_tool_name,
                belief_runtime_affordance_variant_id=composition.belief_runtime_affordance_variant_id,
            )
            collected_items.append(item)
            completed_keys.add(sample_id)
        except Exception as exc:
            failed_items += 1
            storage.append_failure(
                {
                    "task_name": HELP_GATE_ACML_SPEC.task_name,
                    "run_id": context.run_id,
                    "sample_id": sample_id,
                    "qa_record_id": pairing.payload.payload_id,
                    "failed_at": utc_now_iso(),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )
            logger.warning("ACML composition failed for %s: %s", sample_id, exc)

    return HelpGateGenerationOutcome(
        generated=len(collected_items),
        failed_items=failed_items,
        skipped_existing=skipped_existing,
        all_items=tuple(collected_items),
    )


def _summary_fields_for_preflight(
    *,
    plan: HelpGateSourcePlan,
    generated: int,
    skipped_existing: int,
    generated_at: str,
) -> dict:
    return {
        "phase": "preflight",
        "payload_count": plan.payload_count,
        "domain_count": len(plan.payload_domain_distribution()),
        "policy_text_count": plan.policy_text_count,
        "estimated_samples": plan.estimated_samples,
        "generation_readiness": plan.generation_readiness,
        "warnings": plan.warnings(),
        "generated": generated,
        "skipped_existing": skipped_existing,
        "failed_items": 0,
        "composition_version": HELP_GATE_ACML_COMPOSITION_VERSION,
        "generated_at": generated_at,
        **_help_gate_summary_source_fields(plan),
    }


def _summary_fields_for_generation(
    *,
    generation: HelpGateGenerationOutcome,
    plan: HelpGateSourcePlan,
    generated_at: str,
) -> dict:
    # These counters are intentional observability for synthetic-data diversity.
    # If a future refactor accidentally collapses a pool, this summary should
    # make the regression visible instead of silently flattening the dataset.
    will_help_counter = Counter("true" if item.will_help_now else "false" for item in generation.all_items)
    response_counter = Counter(item.response_intent for item in generation.all_items)
    domain_counter = Counter(item.domain_slug for item in generation.all_items)
    bloom_counter = Counter(item.bloom_level or "_unlabeled" for item in generation.all_items)
    reply_tool_counter = Counter(item.reply_tool_name for item in generation.all_items)
    belief_affordance_counter = Counter(
        item.belief_runtime_affordance_variant_id for item in generation.all_items
    )
    return {
        "phase": "acml_generation",
        "payload_count": plan.payload_count,
        "domain_count": len(plan.payload_domain_distribution()),
        "policy_text_count": plan.policy_text_count,
        "estimated_samples": plan.estimated_samples,
        "requested": plan.estimated_samples,
        "generated": generation.generated,
        "failed_items": generation.failed_items,
        "skipped_existing": generation.skipped_existing,
        "pairing_strategy": plan.pairing_strategy,
        "sample_id_policy": "sha256(lineage_tuple)[:20]",
        "composition_version": HELP_GATE_ACML_COMPOSITION_VERSION,
        "generation_readiness": plan.generation_readiness,
        "warnings": plan.warnings(),
        "will_help_now_distribution": dict(will_help_counter),
        "response_intent_distribution": dict(response_counter),
        "domain_distribution": dict(domain_counter),
        "bloom_distribution": dict(bloom_counter),
        "reply_tool_name_distribution": dict(reply_tool_counter),
        "belief_runtime_affordance_distribution": dict(belief_affordance_counter),
        "generated_at": generated_at,
        **_help_gate_summary_source_fields(plan),
    }


def _print_help_gate_report(
    *,
    run_dir: Path,
    summary: dict,
    preflight_only: bool,
) -> None:
    preflight_path = run_dir / "artifacts" / "preflight" / "composition_preflight.json"
    sample_dir = run_dir / "artifacts" / "samples"
    items_dir = run_dir / "artifacts" / "items"
    failures_path = run_dir / "system" / "failures.jsonl"
    run_state_path = run_dir / "work" / "run_state.json"

    print(f"\nComposition preflight written to {preflight_path}")
    print(f"  Payloads:   {summary['payload_count']} ({summary['domain_count']} domains)")
    print(f"  Policy txt: {summary['policy_text_count']}")
    print(f"  Est. ACML:  {summary['estimated_samples']:,}")
    print(f"  Readiness:  {summary['generation_readiness']}")
    for warning in summary["warnings"]:
        print(f"  Warning:    {warning}")
    if preflight_only or summary["generation_readiness"] != "ready":
        return

    print(
        f"\nDone — {summary['generated']} ACML samples in {run_dir}\n"
        f"  samples:  {sample_dir}\n"
        f"  items:    {items_dir}\n"
        f"  state:    {run_state_path}\n"
        f"  skipped:  {summary['skipped_existing']}"
    )
    if summary["failed_items"]:
        print(f"  failures: {failures_path} ({summary['failed_items']} items)")

    # --- Diagnostic distributions ---
    wh = summary.get("will_help_now_distribution", {})
    wh_total = sum(wh.values())
    if wh_total:
        wh_true = wh.get("true", 0)
        print(f"\n  will_help_now: True={wh_true} ({100*wh_true/wh_total:.0f}%)  "
              f"False={wh.get('false', 0)} ({100*wh.get('false',0)/wh_total:.0f}%)")

    ri = summary.get("response_intent_distribution", {})
    if ri:
        print(f"  response_intent distribution ({sum(ri.values())} samples):")
        for intent, cnt in sorted(ri.items(), key=lambda x: -x[1]):
            pct = 100 * cnt / sum(ri.values())
            bar = "█" * max(1, int(pct))
            print(f"    {intent:<22} {cnt:>6} ({pct:>5.1f}%) {bar}")

    dd = summary.get("domain_distribution", {})
    if dd and len(dd) > 1:
        print(f"  domain distribution ({len(dd)} domains):")
        for domain, cnt in sorted(dd.items(), key=lambda x: -x[1]):
            print(f"    {domain:<30} {cnt:>6}")

    bd = summary.get("bloom_distribution", {})
    if bd:
        print(f"  bloom distribution ({len(bd)} levels):")
        for level, cnt in sorted(bd.items(), key=lambda x: -x[1]):
            print(f"    {level:<30} {cnt:>6}")

    rt = summary.get("reply_tool_name_distribution", {})
    if rt:
        names = ", ".join(f"{k}={v}" for k, v in sorted(rt.items()))
        print(f"  reply_tool: {names}")

    ba = summary.get("belief_runtime_affordance_distribution", {})
    if ba:
        variants = ", ".join(f"{k}={v}" for k, v in sorted(ba.items()))
        print(f"  affordance_variant: {variants}")


def run_help_gate_acml(args: argparse.Namespace) -> dict[str, object]:
    request = _help_gate_request_from_args(args)
    try:
        plan = resolve_help_gate_source_plan(request)
    except HelpGateSourcePlanError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    run_dir = HELP_GATE_ACML_SPEC.resolve_run_dir(
        args.run_id,
        output_dir=args.output_dir,
        language=request.language,
    )
    if _help_gate_acml_has_existing_state(run_dir) and not args.resume:
        print(
            f"Help-gate ACML run directory already exists: {run_dir}\n"
            "Use --resume to continue this run, or choose a new --run-id / --output-dir.",
            file=sys.stderr,
        )
        sys.exit(1)
    if args.resume:
        _validate_help_gate_acml_resume_config(run_dir, request=request)

    storage = DerivedStorageManager(run_dir, HELP_GATE_ACML_SPEC.task_name)
    storage.setup()
    existing_state = storage.load_run_state() if args.resume else None
    existing_keys = _list_existing_acml_sample_ids(run_dir)
    config_doc = _help_gate_config_doc(request=request)

    def execute(context) -> DerivedTaskResult:
        started_at = existing_state.started_at if existing_state and existing_state.started_at else context.created_at
        print(f"Loading payloads from {plan.qa_view_path} ...")
        _run_preflight(
            context=context,
            run_id=args.run_id,
            plan=plan,
        )
        print(f"  Loaded {plan.payload_count} payload records")
        print(f"  Found {plan.policy_text_count} policy-text records")

        if plan.policy_text_count == 0:
            print(
                "  No policy-text records found. Run 'generate_policy_text_records' first:\n"
                f"    python policy_text_records_main.py --run-id {request.policy_text_run_id} "
                f"--policy-run-id <policy-run-id> --language {request.language}"
                + (f" --output-dir {request.policy_text_run_dir}" if request.policy_text_run_dir else ""),
                file=sys.stderr,
            )

        if args.preflight_only or plan.generation_readiness != "ready":
            finished_at = utc_now_iso()
            existing_generated = len(existing_keys)
            return DerivedTaskResult(
                status="blocked" if plan.generation_readiness != "ready" else "completed",
                summary={
                    "qa_run_id": request.qa_run_id,
                    "policy_text_run_id": request.policy_text_run_id,
                    "pairing_strategy": plan.pairing_strategy,
                    **_summary_fields_for_preflight(
                        plan=plan,
                        generated=existing_generated,
                        skipped_existing=existing_generated,
                        generated_at=finished_at,
                    ),
                },
                run_state=DerivedRunState(
                    total_items=plan.estimated_samples,
                    completed_count=existing_generated,
                    failed_count=0,
                    started_at=started_at,
                    updated_at=finished_at,
                ),
            )

        generation = _generate_samples(
            context=context,
            storage=storage,
            plan=plan,
            existing_keys=existing_keys,
        )
        finished_at = utc_now_iso()
        return DerivedTaskResult(
            summary={
                "qa_run_id": request.qa_run_id,
                "policy_text_run_id": request.policy_text_run_id,
                **_summary_fields_for_generation(
                    generation=generation,
                    plan=plan,
                    generated_at=finished_at,
                ),
            },
            run_state=DerivedRunState(
                total_items=plan.estimated_samples,
                completed_count=generation.generated,
                failed_count=generation.failed_items,
                started_at=started_at,
                updated_at=finished_at,
            ),
            status="completed_with_failures" if generation.failed_items else "completed",
        )

    def on_error(context, exc: Exception) -> DerivedTaskResult:
        failed_at = utc_now_iso()
        all_items = _load_all_help_gate_items(storage)
        failure_events = storage.count_failure_events()
        started_at = existing_state.started_at if existing_state and existing_state.started_at else context.created_at
        return DerivedTaskResult(
            status="failed",
            summary={
                "phase": "acml_generation",
                "qa_run_id": request.qa_run_id,
                "policy_text_run_id": request.policy_text_run_id,
                "composition_version": HELP_GATE_ACML_COMPOSITION_VERSION,
                "requested": plan.estimated_samples,
                "generated": len(all_items),
                "failed_items": failure_events if failure_events else 1,
                "failed_at": failed_at,
                "error": str(exc),
                **_help_gate_summary_source_fields(plan),
            },
            run_state=DerivedRunState(
                total_items=plan.estimated_samples,
                completed_count=len(all_items),
                failed_count=failure_events if failure_events else 1,
                started_at=started_at,
                updated_at=failed_at,
            ),
        )

    result = run_derived_task(
        spec=HELP_GATE_ACML_SPEC,
        run_id=args.run_id,
        output_dir=args.output_dir,
        language=request.language,
        config_doc=config_doc,
        lineage_doc=plan.lineage_doc(),
        execute=execute,
        on_error=on_error,
    )
    _print_help_gate_report(
        run_dir=run_dir,
        summary=result.summary,
        preflight_only=args.preflight_only,
    )
    return result.summary
