from collections import deque
from datetime import datetime, timezone
import logging

import httpx

from api import LLMClient, LLMResponseError
from models import AnswerItem, Checkpoint, DeadLetterItem, Phase, collect_leaves
from storage import StorageManager

logger = logging.getLogger(__name__)

RECOVERABLE_ITEM_ERRORS = (httpx.HTTPStatusError, httpx.RequestError, LLMResponseError)


class AnswerGenerator:
    def __init__(
        self,
        llm: LLMClient,
        max_attempts: int,
        storage: StorageManager,
        prompts: dict,
        checkpoint: Checkpoint,
    ):
        self.llm = llm
        self.max_attempts = max(1, max_attempts)
        self.storage = storage
        self.p = prompts
        self.cp = checkpoint
        self._attempts: dict[str, int] = {}

    def run(self) -> None:
        tree = self.storage.load_catalog()
        if tree is None:
            raise ValueError("Catalog required before answer generation")

        self._prepare_checkpoint()
        dead_letters = {
            item.question_id or item.item_id for item in self.cp.answer_dead_letters
        }
        pending = deque()
        for path_segments in collect_leaves(tree.root, []):
            if not self.storage.questions_exist(path_segments):
                continue
            qset = self.storage.read_questions(path_segments)
            for question in qset.questions:
                if question.id in dead_letters or self.storage.answer_exists(path_segments, question.id):
                    continue
                pending.append((list(path_segments), question))

        while pending:
            path_segments, question = pending.popleft()
            logger.info("Answering %s [%s]", question.id, question.node_path)

            messages = [
                {"role": "system", "content": self.p["answer_system"]},
                {"role": "user", "content": self.p["answer_user"].format(question=question.text)},
            ]
            try:
                # Long-form answers are the last remaining legacy structured path.
                # We are standardizing new structured outputs on tool calls, but
                # this call stays on chat_json_result until we finish a more
                # targeted migration for long answer payloads and reasoning capture.
                response = self.llm.chat_json_result(messages)
                answer_text = str(response.data.get("answer", "")).strip()
                if not answer_text:
                    raise LLMResponseError("Model returned empty answer")

                answer = AnswerItem(
                    question_id=question.id,
                    question=question.text,
                    answer=answer_text,
                    reasoning_content=response.reasoning_content,
                    bloom_level=question.bloom_level,
                    node_path=question.node_path,
                )
                self.storage.write_answer(path_segments, answer)
            except RECOVERABLE_ITEM_ERRORS as exc:
                if self._record_failure(question.id, question.node_path, exc):
                    pending.append((path_segments, question))
                continue

        self.cp.phase = Phase.ANSWER_GENERATION  # stays, signals completion
        self.cp.completed = True
        self._save()

    def _prepare_checkpoint(self) -> None:
        self.cp.phase = Phase.ANSWER_GENERATION
        self.cp.completed = False
        self.cp.knowledge_tree = None
        self.cp.catalog_frontier = []

    def _record_failure(self, question_id: str, node_path: str, exc: Exception) -> bool:
        attempt = self._attempts.get(question_id, 0) + 1
        self._attempts[question_id] = attempt

        timestamp = datetime.now(timezone.utc).isoformat()
        action = "retry"
        if attempt >= self.max_attempts:
            action = "dead_letter"
            self._attempts.pop(question_id, None)
            self.cp.answer_dead_letters = [
                item for item in self.cp.answer_dead_letters if item.item_id != question_id
            ]
            self.cp.answer_dead_letters.append(DeadLetterItem(
                stage=Phase.ANSWER_GENERATION.value,
                item_id=question_id,
                node_path=node_path,
                question_id=question_id,
                attempts=attempt,
                error_type=type(exc).__name__,
                error_message=str(exc),
                last_failed_at=timestamp,
            ))
            logger.error(
                "Answer generation dead-lettered %s after %d attempts: %s",
                question_id,
                attempt,
                exc,
            )
        else:
            logger.warning(
                "Answer generation failed for %s (%d/%d): %s",
                question_id,
                attempt,
                self.max_attempts,
                exc,
            )

        self.storage.append_failure_event({
            "ts": timestamp,
            "stage": Phase.ANSWER_GENERATION.value,
            "item_id": question_id,
            "node_path": node_path,
            "question_id": question_id,
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
