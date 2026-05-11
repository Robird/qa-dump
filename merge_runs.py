#!/usr/bin/env python3
"""Merge QA view JSONL datasets from multiple runs."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import TextIO

from fs_utils import atomic_write_json
from qa_view import QAViewLayout, QAViewReader
from task_contracts import (
    build_qa_view_manifest,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge one or more QA run views into a single dataset.jsonl",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="QA run/view directories or dataset.jsonl files with a sibling QA manifest",
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


def main() -> None:
    args = parse_args()
    output_layout = QAViewLayout.from_view_dir(args.output_dir)
    output_layout.view_dir.mkdir(parents=True, exist_ok=True)
    output_layout.domains_dir.mkdir(parents=True, exist_ok=True)

    seen_lines: set[str] = set()
    sources: list[dict] = []
    languages: set[str] = set()
    domain_names: dict[str, str] = {}
    domain_counts: dict[str, int] = defaultdict(int)
    domain_paths: dict[str, Path] = {}
    domain_handles: dict[str, TextIO] = {}
    dataset_tmp = output_layout.dataset_path.with_suffix(output_layout.dataset_path.suffix + ".tmp")
    dataset_tmp.parent.mkdir(parents=True, exist_ok=True)

    with dataset_tmp.open("w", encoding="utf-8") as dataset_handle:
        try:
            for raw_input in args.inputs:
                reader = QAViewReader.from_input(raw_input)
                language = reader.manifest.get("language")
                if language:
                    languages.add(language)
                records_count = 0
                kept = 0

                for _, record in reader.iter_records():
                    records_count += 1
                    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
                    if args.dedupe_exact and line in seen_lines:
                        continue
                    seen_lines.add(line)
                    slug = record.get("domain_slug", "")
                    if not slug:
                        raise ValueError(f"Merged QA record is missing domain_slug: {record}")
                    domain = record.get("domain", "")
                    existing_domain = domain_names.setdefault(slug, domain)
                    if domain and existing_domain and domain != existing_domain:
                        raise ValueError(
                            f"Domain slug {slug!r} has conflicting names: {existing_domain!r} vs {domain!r}"
                        )

                    domain_path = domain_paths.get(slug)
                    if domain_path is None:
                        domain_path = output_layout.domain_path(slug)
                        domain_path.parent.mkdir(parents=True, exist_ok=True)
                        domain_paths[slug] = domain_path
                        domain_handles[slug] = domain_path.with_suffix(domain_path.suffix + ".tmp").open(
                            "w",
                            encoding="utf-8",
                        )

                    raw_line = json.dumps(record, ensure_ascii=False) + "\n"
                    domain_handles[slug].write(raw_line)
                    dataset_handle.write(raw_line)
                    domain_counts[slug] += 1
                    kept += 1

                sources.append({
                    "input": raw_input,
                    "dataset": str(reader.layout.dataset_path.resolve()),
                    "manifest": str(reader.layout.manifest_path.resolve()),
                    "records": records_count,
                    "kept": kept,
                })
        finally:
            for handle in domain_handles.values():
                handle.close()

    for slug, domain_path in domain_paths.items():
        tmp_path = domain_path.with_suffix(domain_path.suffix + ".tmp")
        tmp_path.replace(domain_path)
    dataset_tmp.replace(output_layout.dataset_path)

    if len(languages) > 1:
        raise ValueError(f"Cannot merge QA views with mixed languages: {sorted(languages)}")
    language = next(iter(languages), "")

    domain_summaries: list[dict] = []
    for slug in sorted(domain_counts):
        domain_path = domain_paths[slug]
        domain_summaries.append({
            "domain": domain_names.get(slug, ""),
            "slug": slug,
            "records": domain_counts[slug],
            "file": str(domain_path.relative_to(output_layout.view_dir)),
        })
    manifest = build_qa_view_manifest(
        args.merged_id,
        language,
        domain_summaries,
        extra_fields={
            "merged_id": args.merged_id,
            "dedupe_exact": args.dedupe_exact,
            "sources": sources,
        },
    )
    atomic_write_json(
        output_layout.manifest_path,
        manifest,
    )


if __name__ == "__main__":
    main()
