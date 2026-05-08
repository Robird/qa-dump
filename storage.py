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
        _atomic_write(self.checkpoint_path, cp.model_dump_json(indent=2))

    def load_checkpoint(self) -> Optional[Checkpoint]:
        if not self.checkpoint_path.exists():
            return None
        raw = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        return Checkpoint(**raw)

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

    def save_catalog(self, tree: KnowledgeTree) -> None:
        _atomic_write(self.base / "catalog.json", tree.model_dump_json(indent=2, ensure_ascii=False))

    # --- Questions ---

    def write_questions(self, path_segments: list[str], qset: QuestionSet) -> None:
        d = self.ensure_node_dir(path_segments)
        _atomic_write(d / "_questions.json", qset.model_dump_json(indent=2, ensure_ascii=False))

    def read_questions(self, path_segments: list[str]) -> QuestionSet:
        raw = json.loads((self.node_dir(path_segments) / "_questions.json").read_text(encoding="utf-8"))
        return QuestionSet(**raw)

    # --- Answers ---

    def answers_dir(self, path_segments: list[str]) -> Path:
        d = self.node_dir(path_segments) / "answers"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_answer(self, path_segments: list[str], answer: AnswerItem) -> None:
        d = self.answers_dir(path_segments)
        _atomic_write(d / f"{answer.question_id}.json", answer.model_dump_json(indent=2, ensure_ascii=False))
