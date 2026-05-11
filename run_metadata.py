"""Shared helpers for run-root metadata and lifecycle state."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fs_utils import atomic_write_json
from task_contracts import make_run_name


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_run_doc(
    *,
    task_family: str,
    run_id: str,
    language: str | None,
    run_scope: str,
    status: str,
    created_at: str,
    updated_at: str,
    produces: list[dict] | None = None,
    schema_version: str = "1.0",
    spec_version: str | None = None,
    extra_fields: Optional[dict] = None,
) -> dict:
    run_doc = {
        "task_family": task_family,
        "run_name": make_run_name(task_family, run_id),
        "run_id": run_id,
        "run_scope": run_scope,
        "status": status,
        "schema_version": schema_version,
        "created_at": created_at,
        "updated_at": updated_at,
        "produces": produces or [],
    }
    if language is not None:
        run_doc["language"] = language
    if spec_version is not None:
        run_doc["spec_version"] = spec_version
    if extra_fields:
        run_doc.update(extra_fields)
    return run_doc


def write_root_metadata(
    run_root: str | Path,
    *,
    run_doc: dict,
    config_doc: dict,
    lineage_doc: dict,
) -> None:
    root = Path(run_root)
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(root / "run.json", run_doc)
    atomic_write_json(root / "config.json", config_doc)
    atomic_write_json(root / "lineage.json", lineage_doc)


def load_run_doc(run_root: str | Path) -> Optional[dict]:
    path = Path(run_root) / "run.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_config_doc(run_root: str | Path) -> Optional[dict]:
    path = Path(run_root) / "config.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_run_manifest(
    *,
    task_family: str,
    run_id: str,
    updated_at: str,
    summary: Optional[dict] = None,
    outputs: Optional[dict] = None,
    schema_version: str = "1.0",
    extra_fields: Optional[dict] = None,
) -> dict:
    manifest = {
        "task_family": task_family,
        "run_id": run_id,
        "schema_version": schema_version,
        "updated_at": updated_at,
        "summary": summary or {},
        "outputs": outputs or {},
    }
    if extra_fields:
        manifest.update(extra_fields)
    return manifest


def write_run_manifest(run_root: str | Path, manifest_doc: dict) -> None:
    atomic_write_json(Path(run_root) / "manifest.json", manifest_doc)


def load_run_manifest(run_root: str | Path) -> Optional[dict]:
    path = Path(run_root) / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def validate_run_doc(
    run_doc: dict,
    *,
    task_family: str | None = None,
    run_id: str | None = None,
    language: str | None = None,
    run_scope: str | None = None,
) -> None:
    expected = {
        "task_family": task_family,
        "run_id": run_id,
        "language": language,
        "run_scope": run_scope,
    }
    for field, expected_value in expected.items():
        if expected_value is None:
            continue
        actual = run_doc.get(field)
        if actual != expected_value:
            raise ValueError(
                f"Run metadata mismatch for {field}: expected {expected_value!r}, got {actual!r}"
            )


def require_run_doc(
    run_root: str | Path,
    *,
    task_family: str | None = None,
    run_id: str | None = None,
    language: str | None = None,
    run_scope: str | None = None,
) -> dict:
    run_doc = load_run_doc(run_root)
    if run_doc is None:
        raise FileNotFoundError(f"Missing run.json under {Path(run_root)}")
    validate_run_doc(
        run_doc,
        task_family=task_family,
        run_id=run_id,
        language=language,
        run_scope=run_scope,
    )
    return run_doc


def set_run_status(
    run_root: str | Path,
    status: str,
    *,
    updated_at: str | None = None,
    extra_run_fields: Optional[dict] = None,
) -> dict:
    root = Path(run_root)
    current = load_run_doc(root)
    if current is None:
        raise FileNotFoundError(f"Missing run.json under {root}")
    current["status"] = status
    current["updated_at"] = updated_at or utc_now_iso()
    if extra_run_fields:
        current.update(extra_run_fields)
    atomic_write_json(root / "run.json", current)
    return current
