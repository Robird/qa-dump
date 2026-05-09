import logging

from api import LLMClient
from models import AnswerItem, Checkpoint, Phase
from storage import StorageManager

logger = logging.getLogger(__name__)


class AnswerGenerator:
    def __init__(
        self,
        llm: LLMClient,
        storage: StorageManager,
        prompts: dict,
        checkpoint: Checkpoint,
    ):
        self.llm = llm
        self.storage = storage
        self.p = prompts
        self.cp = checkpoint

    def run(self) -> None:
        tree = self.cp.knowledge_tree
        if tree is None:
            raise ValueError("Knowledge tree required in checkpoint")

        done = set(self.cp.answers_done)

        while self.cp.answer_queue:
            entry = self.cp.answer_queue[0]
            qid = entry["question_id"]
            path_str = entry.get("node_path", "")
            text = entry.get("text", "")
            bloom_level = entry.get("bloom_level", "")

            if qid in done:
                self.cp.answer_queue.pop(0)
                continue

            logger.info("Answering %s [%s]", qid, path_str)

            messages = [
                {"role": "system", "content": self.p["answer_system"]},
                {"role": "user", "content": self.p["answer_user"].format(question=text)},
            ]
            response = self.llm.chat_json_result(messages)
            result = response.data

            answer = AnswerItem(
                question_id=qid,
                question=text,
                answer=result.get("answer", ""),
                reasoning_content=response.reasoning_content,
                bloom_level=bloom_level,
                node_path=path_str,
            )

            path_segments = path_str.split("/") if path_str else []
            self.storage.write_answer(path_segments, answer)

            self.cp.answer_queue.pop(0)
            self.cp.answers_done.append(qid)
            self._save()

        self.cp.phase = Phase.ANSWER_GENERATION  # stays, signals completion
        self._save()

    def _save(self) -> None:
        self.storage.save_checkpoint(self.cp)
