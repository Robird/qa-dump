"""Payload source abstraction for derived-data tasks.

Normalises source QA data (and later other payload families) into a
reusable PayloadRecord shape so that policy composition can operate on
a uniform contract regardless of the underlying dataset.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Iterator, Optional

from pydantic import BaseModel
from qa_view import QAViewReader
from task_contracts import make_qa_sample_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Payload record
# ---------------------------------------------------------------------------

class PayloadRecord(BaseModel):
    payload_type: str = "question"
    payload_id: str = ""
    derived_from_question_id: str = ""
    request_text: str = ""
    fulfillment_content: str = ""
    domain_slug: str = ""
    node_path: str = ""
    bloom_level: str = ""
    source_path: str = ""


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------

class PayloadAdapter(ABC):
    @abstractmethod
    def iter_payloads(
        self,
        domain_slug: Optional[str] = None,
        bloom_filter: Optional[set[str]] = None,
        max_records: Optional[int] = None,
    ) -> Iterator[PayloadRecord]: ...

    @abstractmethod
    def discover(
        self,
        domain_slug: Optional[str] = None,
        bloom_filter: Optional[set[str]] = None,
        max_records: Optional[int] = None,
    ) -> list[PayloadRecord]: ...

    @abstractmethod
    def get(self, payload_id: str) -> Optional[PayloadRecord]: ...


# ---------------------------------------------------------------------------
# QA payload adapter (manifest-first)
# ---------------------------------------------------------------------------

class QAPayloadAdapter(PayloadAdapter):
    """Reads payload records from a QA run's export view.

    Uses ``views/<QA_VIEW_ID>/manifest.json`` as the authority for which domain
    files exist, then streams records from the referenced JSONL files.
    """

    def __init__(self, qa_run_dir: str):
        self.reader = QAViewReader.from_input(qa_run_dir)

    @property
    def manifest(self) -> dict:
        return self.reader.manifest

    def domain_slugs(self) -> list[str]:
        return self.reader.domain_slugs()

    def iter_payloads(
        self,
        domain_slug: Optional[str] = None,
        bloom_filter: Optional[set[str]] = None,
        max_records: Optional[int] = None,
    ) -> Iterator[PayloadRecord]:
        self.manifest  # ensure loaded
        if max_records == 0:
            return

        domain_slugs = set(self.reader.domain_slugs())
        if domain_slug and domain_slug not in domain_slugs:
            logger.warning("Domain %s not found in QA view, skipping", domain_slug)
            return

        yielded = 0
        for slug, raw in self.reader.iter_records(domain_slug=domain_slug, ignore_invalid=True):
            filepath = self.reader.domain_path(slug)
            bloom = raw.get("bloom_level", "")
            if bloom_filter and bloom not in bloom_filter:
                continue

            payload_id = raw.get("id") or make_qa_sample_id(
                raw.get("run_id", ""),
                slug,
                raw.get("question_id", ""),
            )
            yield PayloadRecord(
                payload_type="question",
                payload_id=payload_id,
                derived_from_question_id=raw.get("question_id", ""),
                request_text=raw.get("question", ""),
                fulfillment_content=raw.get("answer", ""),
                domain_slug=slug,
                node_path=raw.get("node_path", ""),
                bloom_level=bloom,
                source_path=str(filepath),
            )

            yielded += 1
            if max_records is not None and yielded >= max_records:
                return

    def discover(
        self,
        domain_slug: Optional[str] = None,
        bloom_filter: Optional[set[str]] = None,
        max_records: Optional[int] = None,
    ) -> list[PayloadRecord]:
        return list(
            self.iter_payloads(
                domain_slug=domain_slug,
                bloom_filter=bloom_filter,
                max_records=max_records,
            )
        )

    def get(self, payload_id: str) -> Optional[PayloadRecord]:
        for rec in self.iter_payloads():
            if rec.payload_id == payload_id or rec.derived_from_question_id == payload_id:
                return rec
        return None
