import logging

from api import LLMClient
from models import (
    Checkpoint,
    KnowledgeNode,
    Phase,
    QuestionItem,
    QuestionSet,
    collect_leaves,
    get_node_by_path,
)
from prompts import get_prompts
from storage import StorageManager

logger = logging.getLogger(__name__)


class QuestionGenerator:
    def __init__(
        self,
        llm: LLMClient,
        count: int,
        storage: StorageManager,
        prompts: dict,
        checkpoint: Checkpoint,
    ):
        self.llm = llm
        self.count = count
        self.storage = storage
        self.p = prompts
        self.cp = checkpoint

    def run(self) -> None:
        tree = self.cp.knowledge_tree
        if tree is None:
            raise ValueError("Knowledge tree required in checkpoint")

        if not self.cp.leaf_queue:
            leaf_paths = collect_leaves(tree.root, [])
            self.cp.leaf_queue = ["/".join(p) for p in leaf_paths]
            self._save()

        done = set(self.cp.questions_done)

        while self.cp.leaf_queue:
            path_str = self.cp.leaf_queue[0]
            if path_str in done:
                self.cp.leaf_queue.pop(0)
                continue

            path_segments = path_str.split("/") if path_str else []
            leaf = get_node_by_path(tree.root, list(path_segments))

            logger.info("Generating questions for: %s", path_str)

            messages = [
                {"role": "system", "content": self.p["question_system"].format(count=self.count)},
                {"role": "user", "content": self.p["question_user"].format(
                    name=leaf.name, description=leaf.description, count=self.count
                )},
            ]
            result = self.llm.chat_json(messages, max_tokens=4096)

            questions = self._parse_questions(result, path_str)
            qset = QuestionSet(node_path=path_str, questions=questions)
            self.storage.write_questions(path_segments, qset)

            for q in questions:
                self.cp.answer_queue.append({
                    "question_id": q.id,
                    "node_path": path_str,
                    "text": q.text,
                })

            self.cp.leaf_queue.pop(0)
            self.cp.questions_done.append(path_str)
            self._save()

        self.cp.phase = Phase.ANSWER_GENERATION
        self._save()

    @staticmethod
    def _normalize_bloom(val) -> str:
        if isinstance(val, list):
            return ", ".join(str(v) for v in val)
        return str(val) if val else ""

    def _parse_questions(self, result: dict, node_path: str) -> list[QuestionItem]:
        items = []
        for i, q_data in enumerate(result.get("questions", [])):
            items.append(QuestionItem(
                id=f"q{i + 1:04d}",
                text=q_data.get("text", ""),
                bloom_level=self._normalize_bloom(q_data.get("bloom_level", "")),
                node_path=node_path,
            ))
        return items

    def _save(self) -> None:
        self.storage.save_checkpoint(self.cp)
