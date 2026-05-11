"""QA view layout and manifest-first readers."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from task_contracts import QA_VIEW_ID, qa_view_relpath, validate_qa_view_manifest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QAViewLayout:
    view_dir: Path

    @classmethod
    def from_run_dir(cls, run_dir: str | Path) -> "QAViewLayout":
        return cls(Path(run_dir) / qa_view_relpath())

    @classmethod
    def from_view_dir(cls, view_dir: str | Path) -> "QAViewLayout":
        return cls(Path(view_dir))

    @classmethod
    def from_dataset_path(cls, dataset_path: str | Path) -> "QAViewLayout":
        path = Path(dataset_path)
        if path.name != "dataset.jsonl":
            raise ValueError(f"Expected dataset.jsonl, got: {path}")
        return cls(path.parent)

    @property
    def manifest_path(self) -> Path:
        return self.view_dir / "manifest.json"

    @property
    def dataset_path(self) -> Path:
        return self.view_dir / "dataset.jsonl"

    @property
    def domains_dir(self) -> Path:
        return self.view_dir / "domains"

    def domain_path(self, domain_slug: str) -> Path:
        return self.domains_dir / f"{domain_slug}.jsonl"

    def meta_path(self, domain_slug: str) -> Path:
        return self.view_dir / f"{domain_slug}.meta.json"


def resolve_qa_view_layout(value: str | Path) -> QAViewLayout:
    path = Path(value)

    if path.is_file():
        layout = QAViewLayout.from_dataset_path(path)
        if layout.manifest_path.exists():
            return layout
        raise FileNotFoundError(
            f"Could not find sibling manifest.json for QA dataset input: {path}"
        )

    if path.is_dir():
        run_layout = QAViewLayout.from_run_dir(path)
        if run_layout.manifest_path.exists():
            return run_layout

        direct_layout = QAViewLayout.from_view_dir(path)
        if direct_layout.manifest_path.exists():
            return direct_layout

    raise FileNotFoundError(
        f"Could not resolve QA view from {value}. "
        f"Expected a QA view dir, a run dir containing views/{QA_VIEW_ID}, "
        "or a dataset.jsonl file with a sibling manifest.json."
    )


class QAViewReader:
    def __init__(self, layout: QAViewLayout):
        self.layout = layout
        self._manifest: dict | None = None
        self._domain_entries: dict[str, dict] | None = None

    @classmethod
    def from_input(cls, value: str | Path) -> "QAViewReader":
        return cls(resolve_qa_view_layout(value))

    @property
    def manifest(self) -> dict:
        if self._manifest is None:
            manifest_path = self.layout.manifest_path
            if not manifest_path.exists():
                raise FileNotFoundError(
                    f"QA view manifest not found at {manifest_path}"
                )
            self._manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_qa_view_manifest(self._manifest)
        return self._manifest

    def domain_entries(self) -> list[dict]:
        if self._domain_entries is None:
            entries: dict[str, dict] = {}
            for domain_entry in self.manifest.get("domains", []):
                slug = domain_entry.get("slug", "")
                filename = domain_entry.get("file", "")
                if not slug or not filename:
                    raise ValueError(f"Malformed QA view domain entry: {domain_entry}")

                domain_path = self.layout.view_dir / filename
                if not domain_path.exists():
                    raise FileNotFoundError(
                        f"Manifest for QA view references missing domain file: {domain_path}"
                    )
                entries[slug] = domain_entry
            self._domain_entries = entries
        return [self._domain_entries[slug] for slug in sorted(self._domain_entries)]

    def domain_slugs(self) -> list[str]:
        return [entry["slug"] for entry in self.domain_entries()]

    def domain_path(self, domain_slug: str) -> Path:
        entry = self._domain_entries_by_slug().get(domain_slug)
        if entry is None:
            raise KeyError(f"Domain {domain_slug} not found in QA view manifest")
        return self.layout.view_dir / entry["file"]

    def iter_domain_records(self, domain_slug: str, ignore_invalid: bool = False) -> Iterator[dict]:
        path = self.domain_path(domain_slug)
        yield from self._iter_jsonl(path, ignore_invalid=ignore_invalid)

    def iter_records(
        self,
        domain_slug: str | None = None,
        ignore_invalid: bool = False,
    ) -> Iterator[tuple[str, dict]]:
        slugs = [domain_slug] if domain_slug else self.domain_slugs()
        for slug in slugs:
            if slug not in self._domain_entries_by_slug():
                raise KeyError(f"Domain {slug} not found in QA view manifest")
            for record in self.iter_domain_records(slug, ignore_invalid=ignore_invalid):
                yield slug, record

    def _domain_entries_by_slug(self) -> dict[str, dict]:
        self.domain_entries()
        assert self._domain_entries is not None
        return self._domain_entries

    @staticmethod
    def _iter_jsonl(path: Path, ignore_invalid: bool = False) -> Iterator[dict]:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    if not ignore_invalid:
                        raise
                    logger.warning("Skipping invalid JSON line in %s", path)
