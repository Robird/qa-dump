"""Shared filesystem helpers for atomic text/JSON writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def atomic_write_text(path: str | Path, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)


def atomic_write_json(path: str | Path, payload: dict) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False),
    )


def append_jsonl(path: str | Path, record: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_jsonl(path: str | Path, records: Iterable[dict]) -> None:
    atomic_write_text(path, "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records))
