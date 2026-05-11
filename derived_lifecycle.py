"""Thin lifecycle helpers for first-class derived runs."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from derived_storage import DerivedRunState, DerivedStorageManager
from run_paths import resolve_task_run_root
from run_metadata import (
    build_run_doc,
    build_run_manifest,
    load_run_doc,
    set_run_status,
    utc_now_iso,
    write_root_metadata,
    write_run_manifest,
)
from task_contracts import make_artifact_ref, task_run_scope

logger = logging.getLogger(__name__)


def _merge_outputs(base: dict, extra: dict | None) -> dict:
    merged = {
        section: {name: item.copy() for name, item in values.items()}
        for section, values in base.items()
    }
    if extra is None:
        return merged
    for section, values in extra.items():
        section_values = merged.setdefault(section, {})
        for name, item in values.items():
            merged_item = section_values.setdefault(name, {})
            merged_item.update(item)
    return merged


def _system_outputs() -> dict:
    return {
        "system": {
            "run_state": {"path": "work/run_state.json"},
            "failures": {"path": "system/failures.jsonl"},
        }
    }


def _output_ref_kind(section: str) -> str | None:
    if section == "artifacts":
        return "artifact"
    if section == "views":
        return "view"
    return None


def _materialize_outputs(task_family: str, run_id: str, outputs: dict) -> dict:
    materialized = _merge_outputs(outputs, _system_outputs())
    for section, values in materialized.items():
        ref_kind = _output_ref_kind(section)
        if ref_kind is None:
            continue
        for name, item in values.items():
            item.setdefault("artifact_ref", make_artifact_ref(task_family, run_id, ref_kind, name))
    return materialized


@dataclass(frozen=True)
class DerivedTaskSpec:
    task_name: str
    task_family: str
    outputs: dict = field(default_factory=dict)

    @property
    def run_scope(self) -> str:
        return task_run_scope(self.task_family)

    @property
    def produces(self) -> tuple[dict, ...]:
        produced: list[dict] = []
        for section, values in self.outputs.items():
            ref_kind = _output_ref_kind(section)
            if ref_kind is None:
                continue
            for name, item in values.items():
                produced.append(
                    {
                        "kind": ref_kind,
                        "name": name,
                        "path": item["path"],
                    }
                )
        return tuple(produced)

    def resolve_run_dir(
        self,
        run_id: str,
        *,
        language: str | None = None,
        output_dir: str | None = None,
    ) -> Path:
        if output_dir is not None:
            return Path(output_dir)
        return resolve_task_run_root(self.task_family, run_id, language=language)


@dataclass(frozen=True)
class DerivedRunContext:
    spec: DerivedTaskSpec
    run_id: str
    run_dir: Path
    storage: DerivedStorageManager
    language: str | None
    run_scope: str
    created_at: str

    @property
    def task_name(self) -> str:
        return self.spec.task_name

    @property
    def task_family(self) -> str:
        return self.spec.task_family


@dataclass(frozen=True)
class DerivedTaskResult:
    summary: dict
    run_state: DerivedRunState | None = None
    status: str = "completed"
    output_updates: dict | None = None
    extra_run_fields: dict | None = None


def prepare_derived_run(
    *,
    spec: DerivedTaskSpec,
    run_id: str,
    output_dir: str | None = None,
    language: str | None,
    config_doc: dict,
    lineage_doc: dict,
) -> DerivedRunContext:
    root = spec.resolve_run_dir(run_id, language=language, output_dir=output_dir)
    storage = DerivedStorageManager(root, spec.task_name)
    storage.setup()

    existing_run_doc = load_run_doc(root)
    created_at = existing_run_doc.get("created_at") if existing_run_doc else utc_now_iso()
    updated_at = utc_now_iso()
    write_root_metadata(
        root,
        run_doc=build_run_doc(
            task_family=spec.task_family,
            run_id=run_id,
            language=language,
            run_scope=spec.run_scope,
            status="running",
            created_at=created_at,
            updated_at=updated_at,
            produces=list(spec.produces),
        ),
        config_doc=config_doc,
        lineage_doc=lineage_doc,
    )
    return DerivedRunContext(
        spec=spec,
        run_id=run_id,
        run_dir=root,
        storage=storage,
        language=language,
        run_scope=spec.run_scope,
        created_at=created_at,
    )


def finalize_derived_run(
    context: DerivedRunContext,
    *,
    result: DerivedTaskResult,
) -> dict:
    updated_at = (
        result.run_state.updated_at
        if result.run_state is not None and result.run_state.updated_at
        else utc_now_iso()
    )
    if result.run_state is not None:
        context.storage.save_run_state(result.run_state)
    set_run_status(
        context.run_dir,
        result.status,
        updated_at=updated_at,
        extra_run_fields=result.extra_run_fields,
    )
    manifest = build_run_manifest(
        task_family=context.spec.task_family,
        run_id=context.run_id,
        updated_at=updated_at,
        summary=result.summary,
        outputs=_merge_outputs(
            _materialize_outputs(context.spec.task_family, context.run_id, context.spec.outputs),
            result.output_updates,
        ),
    )
    write_run_manifest(context.run_dir, manifest)
    return manifest


def run_derived_task(
    *,
    spec: DerivedTaskSpec,
    run_id: str,
    output_dir: str | None,
    language: str | None,
    config_doc: dict,
    lineage_doc: dict,
    execute: Callable[[DerivedRunContext], DerivedTaskResult],
    on_error: Callable[[DerivedRunContext, Exception], DerivedTaskResult],
) -> DerivedTaskResult:
    context = prepare_derived_run(
        spec=spec,
        run_id=run_id,
        output_dir=output_dir,
        language=language,
        config_doc=config_doc,
        lineage_doc=lineage_doc,
    )
    try:
        result = execute(context)
    except Exception as exc:
        logger.exception("%s failed for run %s", spec.task_name, run_id)
        context.storage.append_failure(
            {
                "task_name": context.task_name,
                "run_id": context.run_id,
                "failed_at": utc_now_iso(),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        finalize_derived_run(context, result=on_error(context, exc))
        raise
    finalize_derived_run(context, result=result)
    return result
