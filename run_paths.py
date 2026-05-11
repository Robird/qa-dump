from __future__ import annotations

from pathlib import Path

from task_contracts import (
    HELP_GATE_TASK_FAMILY,
    POLICY_TASK_FAMILY,
    QA_TASK_FAMILY,
    QA_VIEW_ID,
    make_run_name,
    task_run_scope,
)


def run_dir_name(task_family: str, run_id: str) -> str:
    return make_run_name(task_family, run_id)


def resolve_task_run_root(
    task_family: str,
    run_id: str,
    *,
    language: str | None = None,
) -> Path:
    run_scope = task_run_scope(task_family)
    if run_scope == "shared":
        return Path("./output/shared/runs") / run_dir_name(task_family, run_id)
    if not language:
        raise ValueError("language is required for language-scoped runs")
    return Path(f"./output/{language}/runs") / run_dir_name(task_family, run_id)


def resolve_task_run_input(
    task_family: str,
    run_id: str,
    *,
    language: str | None = None,
    run_dir: str | None = None,
) -> Path:
    if run_dir:
        return Path(run_dir)
    return resolve_task_run_root(task_family, run_id, language=language)


def resolve_qa_run_root(language: str, run_id: str, output_dir: str | None = None) -> Path:
    if output_dir:
        return Path(output_dir)
    return resolve_task_run_root(
        QA_TASK_FAMILY,
        run_id,
        language=language,
    )


def resolve_policy_run_root(run_id: str, output_dir: str | None = None) -> Path:
    if output_dir:
        return Path(output_dir)
    return resolve_task_run_root(
        POLICY_TASK_FAMILY,
        run_id,
    )


def resolve_help_gate_run_root(language: str, run_id: str, output_dir: str | None = None) -> Path:
    if output_dir:
        return Path(output_dir)
    return resolve_task_run_root(
        HELP_GATE_TASK_FAMILY,
        run_id,
        language=language,
    )


def work_dir(run_root: str | Path) -> Path:
    return Path(run_root) / "work"


def artifacts_dir(run_root: str | Path) -> Path:
    return Path(run_root) / "artifacts"


def views_dir(run_root: str | Path) -> Path:
    return Path(run_root) / "views"


def system_dir(run_root: str | Path) -> Path:
    return Path(run_root) / "system"


def qa_domains_dir(run_root: str | Path) -> Path:
    return work_dir(run_root) / "domains"


def qa_view_dir(run_root: str | Path, view_id: str = QA_VIEW_ID) -> Path:
    return views_dir(run_root) / view_id


def ensure_run_dirs(run_root: str | Path) -> None:
    root = Path(run_root)
    root.mkdir(parents=True, exist_ok=True)
    work_dir(root).mkdir(parents=True, exist_ok=True)
    artifacts_dir(root).mkdir(parents=True, exist_ok=True)
    views_dir(root).mkdir(parents=True, exist_ok=True)
    system_dir(root).mkdir(parents=True, exist_ok=True)
