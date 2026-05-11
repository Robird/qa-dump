"""Shared machine-readable contracts for task families and exported views."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

RunScope = Literal["shared", "language"]

QA_TASK_FAMILY = "qa_corpus"
POLICY_TASK_FAMILY = "policy_records"
HELP_GATE_TASK_FAMILY = "help_gate_augment"

TASK_FAMILY_RUN_SCOPES: dict[str, RunScope] = {
    QA_TASK_FAMILY: "language",
    POLICY_TASK_FAMILY: "shared",
    HELP_GATE_TASK_FAMILY: "language",
}

QA_VIEW_ID = "qa_export_sft_v1"
QA_EXPORT_FORMAT = "qa-dump.sft.jsonl"
QA_EXPORT_FORMAT_VERSION = 1
QA_EXPORT_SCHEMA_VERSION = 2


def make_run_name(task_family: str, run_id: str) -> str:
    return f"{task_family}--{run_id}"


def make_artifact_ref(task_family: str, run_id: str, ref_kind: str, name: str) -> str:
    return f"{task_family}:{run_id}:{ref_kind}:{name}"


def make_qa_sample_id(run_id: str, domain_slug: str, question_id: str) -> str:
    return f"{QA_TASK_FAMILY}:{run_id}:{QA_VIEW_ID}:{domain_slug}:{question_id}"


def qa_view_relpath(view_id: str = QA_VIEW_ID) -> Path:
    return Path("views") / view_id


def task_run_scope(task_family: str) -> RunScope:
    try:
        return TASK_FAMILY_RUN_SCOPES[task_family]
    except KeyError as exc:
        raise ValueError(f"Unknown task family: {task_family}") from exc


def build_qa_view_manifest(
    run_id: str,
    language: str,
    domain_summaries: list[dict],
    *,
    extra_fields: dict | None = None,
) -> dict:
    ordered = sorted(domain_summaries, key=lambda item: item["slug"])
    total_records = sum(item["records"] for item in ordered)
    manifest = {
        "format": QA_EXPORT_FORMAT,
        "format_version": QA_EXPORT_FORMAT_VERSION,
        "export_schema_version": QA_EXPORT_SCHEMA_VERSION,
        "task_family": QA_TASK_FAMILY,
        "run_id": run_id,
        "view_id": QA_VIEW_ID,
        "language": language,
        "total_records": total_records,
        "domains": ordered,
        "fields": [
            "id",
            "run_id",
            "task_family",
            "view_id",
            "question_id",
            "messages",
            "question",
            "answer",
            "language",
            "domain",
            "domain_slug",
            "node_path",
            "bloom_level",
        ],
    }
    if extra_fields:
        manifest.update(extra_fields)
    return manifest


def validate_qa_view_manifest(manifest: dict) -> None:
    if manifest.get("format") != QA_EXPORT_FORMAT:
        raise ValueError(f"Unsupported manifest format: {manifest.get('format')}")
    if manifest.get("format_version") != QA_EXPORT_FORMAT_VERSION:
        raise ValueError(f"Unsupported QA export format version: {manifest.get('format_version')}")
    if manifest.get("export_schema_version") != QA_EXPORT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported QA export schema version: {manifest.get('export_schema_version')}"
        )
    if manifest.get("view_id") != QA_VIEW_ID:
        raise ValueError(f"Unsupported QA view: {manifest.get('view_id')}")
    if manifest.get("task_family") != QA_TASK_FAMILY:
        raise ValueError(f"Unsupported task family for QA view: {manifest.get('task_family')}")
