import json
from pathlib import Path
from typing import Optional

from models import Checkpoint, KnowledgeTree, collect_leaves
from storage import StorageManager


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)


def _to_jsonl(records: list[dict]) -> str:
    if not records:
        return ""
    return "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)


class DatasetExporter:
    def __init__(self, output_dir: str, run_id: str):
        self.base = Path(output_dir)
        self.run_id = run_id
        self.base.mkdir(parents=True, exist_ok=True)

    def _meta_path(self, domain_slug: str) -> Path:
        return self.base / f"{domain_slug}.meta.json"

    def _load_cached_summary(self, domain_slug: str) -> Optional[dict]:
        meta_path = self._meta_path(domain_slug)
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def export_domain(
        self,
        storage: StorageManager,
        tree: KnowledgeTree,
        language: str,
        checkpoint: Optional[Checkpoint] = None,
    ) -> dict:
        domain = tree.domain
        domain_slug = tree.root.slug
        export_path = self.base / f"{domain_slug}.jsonl"
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
                    "id": f"{self.run_id}:{domain_slug}:{question.id}",
                    "run_id": self.run_id,
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

        _atomic_write(export_path, _to_jsonl(records))
        summary = {
            "domain": domain,
            "slug": domain_slug,
            "records": len(records),
            "file": export_path.name,
            "question_dead_letters": len(question_dead_letters),
            "answer_dead_letters": len(answer_dead_letters),
        }
        _atomic_write(
            self._meta_path(domain_slug),
            json.dumps(summary, indent=2, ensure_ascii=False),
        )
        return summary

    def export_run(self, domain_summaries: list[dict], language: str) -> dict:
        ordered = sorted(domain_summaries, key=lambda item: item["slug"])
        combined = []
        total_records = 0

        for summary in ordered:
            content = (self.base / summary["file"]).read_text(encoding="utf-8")
            if content:
                combined.append(content if content.endswith("\n") else content + "\n")
            total_records += summary["records"]

        _atomic_write(self.base / "dataset.jsonl", "".join(combined))

        manifest = {
            "format": "qa-dump.sft.jsonl",
            "format_version": 1,
            "run_id": self.run_id,
            "language": language,
            "total_records": total_records,
            "domains": ordered,
            "fields": [
                "id",
                "run_id",
                "question_id",
                "messages",
                "question",
                "answer",
                "language",
                "domain",
                "domain_slug",
                "node_path",
                "bloom_level",
            ],
        }
        _atomic_write(
            self.base / "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False),
        )
        return manifest
