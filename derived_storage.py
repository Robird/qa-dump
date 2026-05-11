"""Lightweight storage utilities for first-class derived runs.

Run layout:
- ``run.json`` / ``config.json`` / ``lineage.json`` / ``manifest.json`` at run root
- ``work/run_state.json`` for compact operational state
- ``artifacts/items/<item_key>.json`` as the completion ledger
- ``views/export.jsonl`` as a rebuildable projection from items
- ``system/failures.jsonl`` as append-only failure log
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

from fs_utils import append_jsonl, atomic_write_json, atomic_write_text, write_jsonl
from pydantic import BaseModel
from run_paths import ensure_run_dirs


def _sanitize_key(key: str) -> str:
    return quote(key, safe="")


def _restore_key(name: str) -> str:
    return unquote(name)


# ---------------------------------------------------------------------------
# Compact run state
# ---------------------------------------------------------------------------

class DerivedRunState(BaseModel):
    """Compact run metadata.  Does NOT store completed_keys or failed_keys —
    the filesystem is the completion ledger."""
    task_name: str = ""
    run_id: str = ""
    source_run_id: str = ""
    total_items: int = 0
    completed_count: int = 0
    failed_count: int = 0
    started_at: str = ""
    updated_at: str = ""
    last_cursor: str = ""


# ---------------------------------------------------------------------------
# Storage manager
# ---------------------------------------------------------------------------

class DerivedStorageManager:
    """Manages a first-class derived task run directory."""

    def __init__(self, run_base: str | Path, task_name: str):
        self.task_name = task_name
        self.base = Path(run_base)

    # -- Setup & paths --

    def setup(self) -> None:
        ensure_run_dirs(self.base)
        self.items_dir().mkdir(parents=True, exist_ok=True)

    def work_dir(self) -> Path:
        return self.base / "work"

    def artifacts_dir(self) -> Path:
        return self.base / "artifacts"

    def views_dir(self) -> Path:
        return self.base / "views"

    def system_dir(self) -> Path:
        return self.base / "system"

    def items_dir(self) -> Path:
        return self.artifacts_dir() / "items"

    def _run_state_path(self) -> Path:
        return self.work_dir() / "run_state.json"

    def _export_path(self) -> Path:
        return self.views_dir() / "export.jsonl"

    def _failures_path(self) -> Path:
        return self.system_dir() / "failures.jsonl"

    def run_json_path(self) -> Path:
        return self.base / "run.json"

    def config_path(self) -> Path:
        return self.base / "config.json"

    def lineage_path(self) -> Path:
        return self.base / "lineage.json"

    def export_path(self) -> Path:
        return self._export_path()

    def failures_path(self) -> Path:
        return self._failures_path()

    def run_state_path(self) -> Path:
        return self._run_state_path()

    # -- Item I/O (filesystem ledger) --

    def item_path(self, item_key: str) -> Path:
        return self.items_dir() / f"{_sanitize_key(item_key)}.json"

    def item_exists(self, item_key: str) -> bool:
        return self.item_path(item_key).exists()

    def list_existing_keys(self) -> list[str]:
        items_dir = self.items_dir()
        if not items_dir.exists():
            return []
        return sorted(
            _restore_key(p.stem) for p in items_dir.iterdir() if p.suffix == ".json"
        )

    def write_item(self, item_key: str, data: dict) -> None:
        atomic_write_json(self.item_path(item_key), data)

    def read_item(self, item_key: str) -> Optional[dict]:
        p = self.item_path(item_key)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def write_json(self, relative_path: str | Path, data: dict) -> Path:
        path = self.base / Path(relative_path)
        atomic_write_json(path, data)
        return path

    # -- Export (rebuildable projection) --

    def iter_items(self) -> list[dict]:
        records: list[dict] = []
        for key in self.list_existing_keys():
            data = self.read_item(key)
            if data is not None:
                records.append(data)
        return records

    def rebuild_export_view(self) -> int:
        records = self.iter_items()
        write_jsonl(self._export_path(), records)
        return len(records)

    # -- Failures (append-only) --

    def append_failure(self, event: dict) -> None:
        append_jsonl(self._failures_path(), event)

    # -- Run state (compact, no per-item sets) --

    def load_run_state(self) -> Optional[DerivedRunState]:
        p = self._run_state_path()
        if not p.exists():
            return None
        return DerivedRunState(**json.loads(p.read_text(encoding="utf-8")))

    def save_run_state(self, state: DerivedRunState) -> None:
        atomic_write_text(
            self._run_state_path(),
            state.model_dump_json(indent=2, exclude_defaults=True, exclude_none=True),
        )
