"""Helpers for resolving and validating existing task runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from run_metadata import require_run_doc
from run_paths import resolve_task_run_input


@dataclass(frozen=True)
class ResolvedRun:
    run_dir: Path
    run_doc: dict


def resolve_existing_run(
    task_family: str,
    run_id: str,
    *,
    language: str | None = None,
    run_scope: str | None = None,
    run_dir: str | None = None,
) -> ResolvedRun:
    resolved_dir = resolve_task_run_input(
        task_family,
        run_id,
        language=language,
        run_dir=run_dir,
    )
    if not resolved_dir.is_dir():
        raise FileNotFoundError(f"Run directory not found: {resolved_dir}")
    run_doc = require_run_doc(
        resolved_dir,
        task_family=task_family,
        run_id=run_id,
        language=language,
        run_scope=run_scope,
    )
    return ResolvedRun(run_dir=resolved_dir, run_doc=run_doc)
