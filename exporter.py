import json
from pathlib import Path

from models import KnowledgeTree, collect_leaves
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

    def export_domain(
        self,
        storage: StorageManager,
        tree: KnowledgeTree,
        language: str,
    ) -> dict:
        domain = tree.domain
        domain_slug = tree.root.slug
        records: list[dict] = []

        for path_segments in sorted(collect_leaves(tree.root, [])):
            qset = storage.read_questions(path_segments)
            for question in qset.questions:
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

        export_path = self.base / f"{domain_slug}.jsonl"
        _atomic_write(export_path, _to_jsonl(records))
        return {
            "domain": domain,
            "slug": domain_slug,
            "records": len(records),
            "file": export_path.name,
        }

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
