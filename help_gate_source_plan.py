"""Executable source-plan contract for help-gate tasks."""

from __future__ import annotations

import json
import random
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from payload_adapter import PayloadRecord, QAPayloadAdapter
from policy_text_contracts import LanguageCode
from policy_text_models import PolicyTextRecord, TEXT_SCHEMA_VERSION, validate_policy_text_record
from qa_view import QAViewReader
from run_paths import resolve_task_run_input
from run_resolver import ResolvedRun, resolve_existing_run
from task_contracts import (
    POLICY_TEXT_TASK_FAMILY,
    QA_TASK_FAMILY,
    QA_EXPORT_SCHEMA_VERSION,
    QA_VIEW_ID,
    make_artifact_ref,
    task_run_scope,
)


HELP_GATE_PAIRING_STRATEGY = "qa_anchor_modulo_policy_text_shuffled"


def interleave_payloads(
    payloads: list[PayloadRecord],
    *,
    seed: int = 42,
) -> list[PayloadRecord]:
    """Deterministic shuffle so ``max_samples`` slices are domain-diverse.

    Uses a fixed seed so the same input always produces the same order.
    This keeps smoke tests reproducible while preventing the
    alphabetically-first domain from eating the entire budget at
    small ``max_samples``.
    """
    result = list(payloads)
    random.Random(seed).shuffle(result)
    return result


class HelpGateSourcePlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class HelpGateSourceRequest:
    language: LanguageCode
    qa_run_id: str
    policy_text_run_id: str
    qa_run_dir: str | None = None
    policy_text_run_dir: str | None = None
    domains: tuple[str, ...] = ()
    bloom_levels: tuple[str, ...] = ()
    max_samples: int | None = None

    def config_fields(self) -> dict:
        return {
            "language": self.language,
            "qa_run_id": self.qa_run_id,
            "policy_text_run_id": self.policy_text_run_id,
            "domains": list(self.domains) if self.domains else None,
            "bloom_levels": list(self.bloom_levels) if self.bloom_levels else None,
            "max_samples": self.max_samples,
        }


@dataclass(frozen=True)
class HelpGatePairing:
    index: int
    payload: PayloadRecord
    policy_text: PolicyTextRecord


@dataclass(frozen=True)
class HelpGateSourcePlan:
    request: HelpGateSourceRequest
    qa_run: ResolvedRun
    policy_text_run: ResolvedRun
    qa_reader: QAViewReader
    payloads: tuple[PayloadRecord, ...]
    policy_text_records: tuple[PolicyTextRecord, ...]
    pairing_strategy: str = HELP_GATE_PAIRING_STRATEGY
    qa_view_id: str = QA_VIEW_ID

    @property
    def qa_view_path(self) -> Path:
        return self.qa_run.run_dir / "views" / self.qa_view_id

    @property
    def payload_count(self) -> int:
        return len(self.payloads)

    @property
    def policy_text_count(self) -> int:
        return len(self.policy_text_records)

    @property
    def estimated_samples(self) -> int:
        return self.payload_count if self.policy_text_count > 0 else 0

    @property
    def generation_readiness(self) -> str:
        return "ready" if self.estimated_samples > 0 else "blocked"

    @property
    def qa_export_schema_version(self) -> int:
        return self.qa_reader.manifest.get("export_schema_version", QA_EXPORT_SCHEMA_VERSION)

    @property
    def policy_text_export_schema_version(self) -> str:
        if self.policy_text_records:
            return self.policy_text_records[0].schema_version
        return TEXT_SCHEMA_VERSION

    def build_plan(self) -> HelpGateSourcePlan:
        return self

    def iter_pairs(self) -> Iterator[HelpGatePairing]:
        if not self.policy_text_records:
            return
        for index, payload in enumerate(self.payloads, start=1):
            yield HelpGatePairing(
                index=index,
                payload=payload,
                policy_text=self.policy_text_records[(index - 1) % len(self.policy_text_records)],
            )

    def payload_domain_distribution(self) -> dict[str, int]:
        return dict(Counter(payload.domain_slug for payload in self.payloads).most_common())

    def payload_bloom_distribution(self) -> dict[str, int]:
        return dict(Counter(payload.bloom_level for payload in self.payloads).most_common())

    def policy_text_will_help_distribution(self) -> dict[str, int]:
        return dict(
            Counter("true" if record.will_help_now else "false" for record in self.policy_text_records).most_common()
        )

    def policy_text_intent_distribution(self) -> dict[str, int]:
        return dict(Counter(record.response_intent for record in self.policy_text_records).most_common())

    def sample_payloads(self, count: int = 5) -> list[PayloadRecord]:
        return list(self.payloads[:count])

    def sample_policy_text_records(self, count: int = 3) -> list[PolicyTextRecord]:
        return list(self.policy_text_records[:count])

    def warnings(self) -> list[str]:
        warnings: list[str] = []
        if not self.payloads:
            warnings.append("No payload records found — check the QA export view.")
        if not self.policy_text_records:
            warnings.append("No policy-text records found — run generate_policy_text_records first.")
        if self.payloads and self.policy_text_records:
            blooms = {payload.bloom_level for payload in self.payloads if payload.bloom_level}
            if len(blooms) < 3:
                warnings.append(f"Only {len(blooms)} bloom levels represented across payloads.")
        return warnings

    def summary_source_fields(self) -> dict:
        return {
            "qa_view_id": self.qa_view_id,
            "qa_export_schema_version": self.qa_export_schema_version,
            "policy_text_export_schema_version": self.policy_text_export_schema_version,
        }

    def lineage_doc(self) -> dict:
        filters = {
            "domains": list(self.request.domains) if self.request.domains else None,
            "bloom_levels": list(self.request.bloom_levels) if self.request.bloom_levels else None,
            "max_samples": self.request.max_samples,
        }
        return {
            "sources": [
                {
                    "task_family": QA_TASK_FAMILY,
                    "run_id": self.request.qa_run_id,
                    "path": str(self.qa_run.run_dir),
                    "use": "payload_adapter",
                    "artifact_ref": make_artifact_ref(QA_TASK_FAMILY, self.request.qa_run_id, "view", QA_VIEW_ID),
                    "filters": filters,
                },
                {
                    "task_family": POLICY_TEXT_TASK_FAMILY,
                    "run_id": self.request.policy_text_run_id,
                    "path": str(self.policy_text_run.run_dir),
                    "use": "policy_text_source",
                    "artifact_ref": make_artifact_ref(
                        POLICY_TEXT_TASK_FAMILY,
                        self.request.policy_text_run_id,
                        "view",
                        "export",
                    ),
                },
            ]
        }


def default_qa_run_dir(language: str, run_id: str) -> Path:
    return resolve_task_run_input(QA_TASK_FAMILY, run_id, language=language)


def default_policy_text_run_dir(language: str, run_id: str) -> Path:
    return resolve_task_run_input(POLICY_TEXT_TASK_FAMILY, run_id, language=language)


def load_policy_text_export_records(run_dir: str | Path) -> list[PolicyTextRecord]:
    path = Path(run_dir) / "views" / "export.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Policy-text export not found: {path}")
    records: list[PolicyTextRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(validate_policy_text_record(json.loads(line)))
            except Exception as exc:
                raise ValueError(
                    "Invalid policy-text export record "
                    f"at {path}:{line_number} for schema {TEXT_SCHEMA_VERSION}: {exc}"
                )
        records.sort(key=lambda record: record.record_id)
    return records


def load_filtered_payloads(
    adapter: QAPayloadAdapter,
    *,
    domains: list[str] | None,
    bloom_levels: list[str] | None,
    max_records: int | None,
) -> list[PayloadRecord]:
    bloom_filter = set(bloom_levels) if bloom_levels else None
    if domains:
        all_payloads: list[PayloadRecord] = []
        for slug in domains:
            remaining = None
            if max_records is not None:
                remaining = max(0, max_records - len(all_payloads))
                if remaining == 0:
                    break
            all_payloads.extend(
                adapter.discover(domain_slug=slug, bloom_filter=bloom_filter, max_records=remaining)
            )
        return all_payloads
    return adapter.discover(bloom_filter=bloom_filter, max_records=max_records)


def build_help_gate_source_plan(
    *,
    request: HelpGateSourceRequest,
    qa_run: ResolvedRun,
    policy_text_run: ResolvedRun,
    qa_reader: QAViewReader,
    policy_text_records: list[PolicyTextRecord],
) -> HelpGateSourcePlan:
    adapter = QAPayloadAdapter(str(qa_run.run_dir))
    # Load *all* matching payloads first, then interleave and slice.
    # This guarantees domain-stratified coverage even when max_samples
    # is smaller than the total pool.
    raw_payloads = load_filtered_payloads(
        adapter,
        domains=list(request.domains) if request.domains else None,
        bloom_levels=list(request.bloom_levels) if request.bloom_levels else None,
        max_records=None,  # shuffle first, slice later
    )
    shuffled = interleave_payloads(raw_payloads)
    if request.max_samples is not None:
        shuffled = shuffled[: request.max_samples]

    policy_text_records = sorted(policy_text_records, key=lambda record: record.record_id)
    return HelpGateSourcePlan(
        request=request,
        qa_run=qa_run,
        policy_text_run=policy_text_run,
        qa_reader=qa_reader,
        payloads=tuple(shuffled),
        policy_text_records=tuple(policy_text_records),
    )


def _resolve_qa_run(request: HelpGateSourceRequest) -> tuple[ResolvedRun, QAViewReader]:
    try:
        qa_run = resolve_existing_run(
            task_family=QA_TASK_FAMILY,
            run_id=request.qa_run_id,
            language=request.language,
            run_scope=task_run_scope(QA_TASK_FAMILY),
            run_dir=request.qa_run_dir,
        )
        qa_reader = QAViewReader.from_input(qa_run.run_dir)
    except (FileNotFoundError, ValueError) as exc:
        qa_run_dir = (
            Path(request.qa_run_dir)
            if request.qa_run_dir
            else default_qa_run_dir(request.language, request.qa_run_id)
        )
        raise HelpGateSourcePlanError(f"Invalid QA run directory {qa_run_dir}: {exc}") from exc
    return qa_run, qa_reader


def _resolve_policy_text_run(
    request: HelpGateSourceRequest,
) -> tuple[ResolvedRun, list[PolicyTextRecord]]:
    try:
        policy_text_run = resolve_existing_run(
            task_family=POLICY_TEXT_TASK_FAMILY,
            run_id=request.policy_text_run_id,
            language=request.language,
            run_scope=task_run_scope(POLICY_TEXT_TASK_FAMILY),
            run_dir=request.policy_text_run_dir,
        )
        policy_text_records = load_policy_text_export_records(policy_text_run.run_dir)
    except (FileNotFoundError, ValueError) as exc:
        policy_text_run_dir = (
            Path(request.policy_text_run_dir)
            if request.policy_text_run_dir
            else default_policy_text_run_dir(request.language, request.policy_text_run_id)
        )
        raise HelpGateSourcePlanError(
            f"Invalid policy-text run directory {policy_text_run_dir}: {exc}\n"
            "Generate policy-text records first, for example:\n"
            f"  python policy_text_records_main.py --run-id {request.policy_text_run_id} "
            f"--policy-run-id <policy-run-id> --language {request.language}"
            + (f" --output-dir {request.policy_text_run_dir}" if request.policy_text_run_dir else "")
        ) from exc
    return policy_text_run, policy_text_records


def resolve_help_gate_source_plan(request: HelpGateSourceRequest) -> HelpGateSourcePlan:
    qa_run, qa_reader = _resolve_qa_run(request)
    policy_text_run, policy_text_records = _resolve_policy_text_run(request)
    return build_help_gate_source_plan(
        request=request,
        qa_run=qa_run,
        policy_text_run=policy_text_run,
        qa_reader=qa_reader,
        policy_text_records=policy_text_records,
    )
