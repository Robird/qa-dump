import json
from pathlib import Path
from typing import Optional

from fs_utils import atomic_write_json, atomic_write_text, write_jsonl
from models import Checkpoint, KnowledgeTree, collect_leaves
from qa_view import QAViewLayout
from storage import StorageManager
from task_contracts import (
    QA_EXPORT_SCHEMA_VERSION,
    QA_TASK_FAMILY,
    QA_VIEW_ID,
    build_qa_view_manifest,
    make_qa_sample_id,
)


class DatasetExporter:
    def __init__(self, output_dir: str, run_id: str):
        self.layout = QAViewLayout.from_view_dir(output_dir)
        self.base = self.layout.view_dir
        self.run_id = run_id
        self.base.mkdir(parents=True, exist_ok=True)
        self.layout.domains_dir.mkdir(parents=True, exist_ok=True)

    def _meta_path(self, domain_slug: str) -> Path:
        return self.layout.meta_path(domain_slug)

    def _load_cached_summary(self, domain_slug: str) -> Optional[dict]:
        meta_path = self._meta_path(domain_slug)
        if not meta_path.exists():
            return None
        summary = json.loads(meta_path.read_text(encoding="utf-8"))
        if summary.get("export_schema_version") != QA_EXPORT_SCHEMA_VERSION:
            return None
        return summary

    def export_domain(
        self,
        storage: StorageManager,
        tree: KnowledgeTree,
        language: str,
        checkpoint: Optional[Checkpoint] = None,
    ) -> dict:
        domain = tree.domain
        domain_slug = tree.root.slug
        export_path = self.layout.domain_path(domain_slug)
        cached = self._load_cached_summary(domain_slug)
        if cached is not None and export_path.exists():
            return cached

        if checkpoint is None:
            checkpoint = storage.load_checkpoint()

        question_dead_letters = set()
        answer_dead_letters = set()
        if checkpoint is not None:
            question_dead_letters = {item.item_id for item in checkpoint.question_dead_letters}
            answer_dead_letters = {
                item.question_id or item.item_id for item in checkpoint.answer_dead_letters
            }

        records: list[dict] = []

        for path_segments in sorted(collect_leaves(tree.root, [])):
            path_str = "/".join(path_segments)
            if not storage.questions_exist(path_segments):
                if path_str in question_dead_letters:
                    continue
                raise FileNotFoundError(f"Missing questions file for completed leaf: {path_str}")

            qset = storage.read_questions(path_segments)
            for question in qset.questions:
                if not storage.answer_exists(path_segments, question.id):
                    if question.id in answer_dead_letters:
                        continue
                    raise FileNotFoundError(f"Missing answer file for completed question: {question.id}")

                answer = storage.read_answer(path_segments, question.id)
                records.append({
                    "id": make_qa_sample_id(self.run_id, domain_slug, question.id),
                    "run_id": self.run_id,
                    "task_family": QA_TASK_FAMILY,
                    "view_id": QA_VIEW_ID,
                    "question_id": question.id,
                    "messages": [
                        {"role": "user", "content": question.text},
                        {"role": "assistant", "content": answer.answer},
                    ],
                    "question": question.text,
                    "answer": answer.answer,
                    "language": language,
                    "domain": domain,
                    "domain_slug": domain_slug,
                    "node_path": question.node_path,
                    "bloom_level": question.bloom_level,
                })

        write_jsonl(export_path, records)
        summary = {
            "export_schema_version": QA_EXPORT_SCHEMA_VERSION,
            "domain": domain,
            "slug": domain_slug,
            "records": len(records),
            "file": str(export_path.relative_to(self.base)),
            "question_dead_letters": len(question_dead_letters),
            "answer_dead_letters": len(answer_dead_letters),
        }
        atomic_write_json(self._meta_path(domain_slug), summary)
        return summary

    def export_run(self, domain_summaries: list[dict], language: str) -> dict:
        ordered = sorted(domain_summaries, key=lambda item: item["slug"])
        combined = []

        for summary in ordered:
            content = (self.base / summary["file"]).read_text(encoding="utf-8")
            if content:
                combined.append(content if content.endswith("\n") else content + "\n")

        atomic_write_text(self.layout.dataset_path, "".join(combined))

        manifest = build_qa_view_manifest(self.run_id, language, ordered)
        atomic_write_json(self.layout.manifest_path, manifest)
        return manifest
