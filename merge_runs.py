#!/usr/bin/env python3
"""Merge exported JSONL datasets from multiple runs."""

import argparse
import json
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge one or more run exports into a single dataset.jsonl",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Run directories or dataset.jsonl files to merge",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory to write merged dataset.jsonl and manifest.json",
    )
    parser.add_argument(
        "--merged-id",
        default="merged",
        help="Identifier written to the merged manifest",
    )
    parser.add_argument(
        "--dedupe-exact",
        action="store_true",
        help="Drop exact duplicate JSON lines while preserving order",
    )
    return parser.parse_args()


def resolve_dataset_path(value: str) -> Path:
    path = Path(value)
    if path.is_file():
        return path
    candidate = path / "exports" / "dataset.jsonl"
    if candidate.exists():
        return candidate
    raise FileNotFoundError(f"Could not find dataset.jsonl under: {value}")


def read_jsonl(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    merged: list[dict] = []
    seen_lines: set[str] = set()
    sources: list[dict] = []

    for raw_input in args.inputs:
        dataset_path = resolve_dataset_path(raw_input)
        records = read_jsonl(dataset_path)
        kept = 0

        for record in records:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            if args.dedupe_exact and line in seen_lines:
                continue
            seen_lines.add(line)
            merged.append(record)
            kept += 1

        sources.append({
            "input": raw_input,
            "dataset": str(dataset_path.resolve()),
            "records": len(records),
            "kept": kept,
        })

    atomic_write(
        output_dir / "dataset.jsonl",
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in merged),
    )
    atomic_write(
        output_dir / "manifest.json",
        json.dumps(
            {
                "format": "qa-dump.sft.jsonl",
                "format_version": 1,
                "merged_id": args.merged_id,
                "total_records": len(merged),
                "dedupe_exact": args.dedupe_exact,
                "sources": sources,
            },
            indent=2,
            ensure_ascii=False,
        ),
    )


if __name__ == "__main__":
    main()
