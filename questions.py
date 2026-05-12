from collections import deque
from datetime import datetime, timezone
import logging

import httpx

from api import LLMClient, LLMResponseError
from models import (
    Checkpoint,
    DeadLetterItem,
    Phase,
    QuestionListResponse,
    QuestionItem,
    QuestionSet,
    collect_leaves,
    get_node_by_path,
    make_question_id,
)
from storage import StorageManager

logger = logging.getLogger(__name__)

RECOVERABLE_ITEM_ERRORS = (httpx.HTTPStatusError, httpx.RequestError, LLMResponseError)


class QuestionGenerator:
    def __init__(
        self,
        llm: LLMClient,
        count: int,
        max_attempts: int,
        storage: StorageManager,
        prompts: dict,
        checkpoint: Checkpoint,
    ):
        self.llm = llm
        self.count = count
        self.max_attempts = max(1, max_attempts)
        self.storage = storage
        self.p = prompts
        self.cp = checkpoint
        self._attempts: dict[str, int] = {}

    def run(self) -> None:
        tree = self.storage.load_catalog()
        if tree is None:
            raise ValueError("Catalog required before question generation")

        self._prepare_checkpoint()
        dead_letters = {item.item_id for item in self.cp.question_dead_letters}
        pending = deque(
            "/".join(path_segments)
            for path_segments in collect_leaves(tree.root, [])
            if "/".join(path_segments) not in dead_letters
            and not self.storage.questions_exist(path_segments)
        )

        while pending:
            path_str = pending.popleft()

            path_segments = path_str.split("/") if path_str else []
            leaf = get_node_by_path(tree.root, list(path_segments))

            logger.info("Generating questions for: %s", path_str)

            messages = [
                {"role": "system", "content": self.p["question_system"].format(count=self.count)},
                {"role": "user", "content": self.p["question_user"].format(
                    name=leaf.name, description=leaf.description, count=self.count
                )},
            ]
            try:
                result = self.llm.chat_structured(
                    messages,
                    output_model=QuestionListResponse,
                    tool_name="submit_questions",
                    tool_description="Submit generated assessment questions for the requested knowledge topic.",
                    temperature=0.3,
                )
                questions = self._parse_questions(result, path_str)
                qset = QuestionSet(node_path=path_str, questions=questions)
                self.storage.write_questions(path_segments, qset)
            except RECOVERABLE_ITEM_ERRORS as exc:
                if self._record_failure(path_str, exc):
                    pending.append(path_str)
                continue

        self.cp.phase = Phase.ANSWER_GENERATION
        self.cp.completed = False
        self._save()

    @staticmethod
    def _normalize_bloom(val) -> str:
        if isinstance(val, list):
            return ", ".join(str(v) for v in val)
        return str(val) if val else ""

    def _parse_questions(self, result: QuestionListResponse, node_path: str) -> list[QuestionItem]:
        items: list[QuestionItem] = []
        seen_texts: set[str] = set()
        for q_data in result.questions:
            text = str(q_data.text).strip()
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            items.append(QuestionItem(
                id=make_question_id(node_path, len(items) + 1),
                text=text,
                bloom_level=self._normalize_bloom(q_data.bloom_level),
                node_path=node_path,
            ))
        if not items:
            raise LLMResponseError("Model returned no usable questions")
        return items

    def _prepare_checkpoint(self) -> None:
        self.cp.phase = Phase.QUESTION_GENERATION
        self.cp.completed = False
        self.cp.knowledge_tree = None
        self.cp.catalog_frontier = []

    def _record_failure(self, path_str: str, exc: Exception) -> bool:
        attempt = self._attempts.get(path_str, 0) + 1
        self._attempts[path_str] = attempt

        timestamp = datetime.now(timezone.utc).isoformat()
        action = "retry"
        if attempt >= self.max_attempts:
            action = "dead_letter"
            self._attempts.pop(path_str, None)
            self.cp.question_dead_letters = [
                item for item in self.cp.question_dead_letters if item.item_id != path_str
            ]
            self.cp.question_dead_letters.append(DeadLetterItem(
                stage=Phase.QUESTION_GENERATION.value,
                item_id=path_str,
                node_path=path_str,
                attempts=attempt,
                error_type=type(exc).__name__,
                error_message=str(exc),
                last_failed_at=timestamp,
            ))
            logger.error(
                "Question generation dead-lettered %s after %d attempts: %s",
                path_str,
                attempt,
                exc,
            )
        else:
            logger.warning(
                "Question generation failed for %s (%d/%d): %s",
                path_str,
                attempt,
                self.max_attempts,
                exc,
            )

        self.storage.append_failure_event({
            "ts": timestamp,
            "stage": Phase.QUESTION_GENERATION.value,
            "item_id": path_str,
            "node_path": path_str,
            "attempt": attempt,
            "max_attempts": self.max_attempts,
            "retryable": True,
            "action": action,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "model": self.llm.model,
        })
        if action == "dead_letter":
            self._save()
        return action == "retry"

    def _save(self) -> None:
        self.storage.save_checkpoint(self.cp)
