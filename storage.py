import json
from pathlib import Path
from typing import Optional

from models import AnswerItem, Checkpoint, KnowledgeNode, KnowledgeTree, QuestionSet


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)


class StorageManager:
    def __init__(self, output_dir: str):
        self.base = Path(output_dir)

    def setup(self) -> None:
        self.base.mkdir(parents=True, exist_ok=True)

    # --- Config ---

    def save_config(self, config: dict) -> None:
        _atomic_write(self.base / "config.json", json.dumps(config, indent=2, ensure_ascii=False))

    # --- Checkpoint ---

    @property
    def checkpoint_path(self) -> Path:
        return self.base / ".checkpoint.json"

    def save_checkpoint(self, cp: Checkpoint) -> None:
        _atomic_write(
            self.checkpoint_path,
            cp.model_dump_json(indent=2, exclude_defaults=True, exclude_none=True),
        )

    def load_checkpoint(self) -> Optional[Checkpoint]:
        if not self.checkpoint_path.exists():
            return None
        raw = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        return Checkpoint(**raw)

    @property
    def failures_path(self) -> Path:
        return self.base / "failures.jsonl"

    def append_failure_event(self, event: dict) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        with self.failures_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    # --- Node directory & metadata ---

    def node_dir(self, path_segments: list[str]) -> Path:
        return self.base.joinpath(*path_segments)

    def ensure_node_dir(self, path_segments: list[str]) -> Path:
        d = self.node_dir(path_segments)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_node(self, path_segments: list[str], node: KnowledgeNode) -> None:
        d = self.ensure_node_dir(path_segments)
        _atomic_write(d / "_node.json", node.model_dump_json(indent=2, ensure_ascii=False))

    def read_node(self, path_segments: list[str]) -> KnowledgeNode:
        raw = json.loads((self.node_dir(path_segments) / "_node.json").read_text(encoding="utf-8"))
        return KnowledgeNode(**raw)

    # --- Catalog ---

    @property
    def catalog_path(self) -> Path:
        return self.base / "catalog.json"

    def save_catalog(self, tree: KnowledgeTree) -> None:
        _atomic_write(self.catalog_path, tree.model_dump_json(indent=2, ensure_ascii=False))

    def load_catalog(self) -> Optional[KnowledgeTree]:
        if not self.catalog_path.exists():
            return None
        raw = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        return KnowledgeTree(**raw)

    # --- Questions ---

    def questions_path(self, path_segments: list[str]) -> Path:
        return self.node_dir(path_segments) / "_questions.json"

    def questions_exist(self, path_segments: list[str]) -> bool:
        return self.questions_path(path_segments).exists()

    def write_questions(self, path_segments: list[str], qset: QuestionSet) -> None:
        d = self.ensure_node_dir(path_segments)
        _atomic_write(d / "_questions.json", qset.model_dump_json(indent=2, ensure_ascii=False))

    def read_questions(self, path_segments: list[str]) -> QuestionSet:
        raw = json.loads(self.questions_path(path_segments).read_text(encoding="utf-8"))
        return QuestionSet(**raw)

    # --- Answers ---

    def answers_dir(self, path_segments: list[str]) -> Path:
        d = self.node_dir(path_segments) / "answers"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def answer_path(self, path_segments: list[str], question_id: str) -> Path:
        return self.node_dir(path_segments) / "answers" / f"{question_id}.json"

    def answer_exists(self, path_segments: list[str], question_id: str) -> bool:
        return self.answer_path(path_segments, question_id).exists()

    def write_answer(self, path_segments: list[str], answer: AnswerItem) -> None:
        d = self.answers_dir(path_segments)
        _atomic_write(d / f"{answer.question_id}.json", answer.model_dump_json(indent=2, ensure_ascii=False))

    def read_answer(self, path_segments: list[str], question_id: str) -> AnswerItem:
        raw = json.loads(self.answer_path(path_segments, question_id).read_text(encoding="utf-8"))
        return AnswerItem(**raw)
