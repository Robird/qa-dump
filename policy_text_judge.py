"""Semantic judge for policy_text candidates."""

from __future__ import annotations

import json
import logging
import re

from api import LLMClient, LLMResponseError
from policy_text_issues import PolicyTextIssue, summarize_issue_messages
from policy_text_models import PolicyTextRealization
from policy_text_preparation import PreparedPolicyTextTask
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# The judge needs enough output budget for reasoning plus the final tool call.
# On DeepSeek, budgets that are too small can end in finish_reason="length"
# before the model emits tool arguments, which looks like a missing tool call.
DEFAULT_POLICY_TEXT_JUDGE_MAX_TOKENS = 1600


class PolicyTextSemanticRejection(LLMResponseError):
    def __init__(self, issues: list[PolicyTextIssue], verdict: "PolicyTextJudgeVerdict"):
        self.issues = tuple(issues)
        self.verdict = verdict
        super().__init__("Policy text realization failed semantic validation: " + summarize_issue_messages(self.issues))


class PolicyTextJudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pass_verdict: bool
    score: int = Field(ge=0, le=5)
    issues: list[str] = Field(default_factory=list)
    repair_instructions: list[str] = Field(default_factory=list)


class PolicyTextSemanticJudge:
    TOOL_NAME = "submit_policy_text_judgment"

    def __init__(
        self,
        llm: LLMClient,
        *,
        language: str,
    ):
        self.llm = llm
        self.language = language

    def evaluate(
        self,
        *,
        task: PreparedPolicyTextTask,
        realization: PolicyTextRealization,
        retry_feedback: tuple[PolicyTextIssue, ...] = (),
    ) -> PolicyTextJudgeVerdict:
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": self._user_prompt(
                    task,
                    realization=realization,
                    retry_feedback=retry_feedback,
                ),
            },
        ]
        logger.debug(
            "PolicyTextSemanticJudge request for %s: %s",
            task.source_policy.record_id,
            _preview_text(messages[1]["content"], limit=800),
        )
        verdict = self._request_verdict(record_id=task.source_policy.record_id, messages=messages)
        logger.debug(
            "PolicyTextSemanticJudge verdict for %s: pass=%s score=%s issues=%s repairs=%s",
            task.source_policy.record_id,
            verdict.pass_verdict,
            verdict.score,
            verdict.issues,
            verdict.repair_instructions,
        )
        if verdict.pass_verdict:
            return verdict
        issues = self._build_semantic_issues(verdict)
        raise PolicyTextSemanticRejection(issues, verdict)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        retry=retry_if_exception_type(ValidationError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _request_verdict(
        self,
        *,
        record_id: str,
        messages: list[dict],
    ) -> PolicyTextJudgeVerdict:
        # Keep the judge on the tool-call path: the verdict belongs in structured
        # tool arguments, not assistant prose. DeepSeek rejects explicit
        # function-style tool_choice on some models, but still accepts tool calls
        # when we omit the field and let the model choose.
        raw = self.llm.chat_tool_call_result(
            messages,
            tool=self._tool_spec(),
            tool_choice=None,
            temperature=0.0,
            max_tokens=DEFAULT_POLICY_TEXT_JUDGE_MAX_TOKENS,
        )
        logger.debug(
            "PolicyTextSemanticJudge tool result for %s: tool=%s content=%r reasoning=%r args=%s",
            record_id,
            raw.tool_name,
            _preview_text(raw.content, limit=220) if raw.content else "",
            _preview_text(raw.reasoning_content, limit=220) if raw.reasoning_content else "",
            raw.arguments,
        )
        try:
            return PolicyTextJudgeVerdict.model_validate(raw.arguments)
        except ValidationError:
            logger.warning(
                "PolicyTextSemanticJudge received invalid tool arguments for %s: %s",
                record_id,
                raw.arguments,
            )
            raise

    def _system_prompt(self) -> str:
        return (
            "You are a strict semantic judge for policy_text."
            " You are not a rewriter."
            " The structured result must be returned via the provided tool call."
            " Keep internal reasoning brief, then call the provided function exactly once."
            " Put the final judgment only in the function arguments."
            " Do not place the verdict in assistant text."
        )

    def _user_prompt(
        self,
        task: PreparedPolicyTextTask,
        *,
        realization: PolicyTextRealization,
        retry_feedback: tuple[PolicyTextIssue, ...],
    ) -> str:
        retry_block = self._retry_feedback_block(retry_feedback)
        candidate_json = json.dumps(realization.model_dump(), ensure_ascii=False, separators=(",", ":"))
        input_json = json.dumps(task.realization_input.model_dump(), ensure_ascii=False, separators=(",", ":"))
        return "".join(
            [
                f"Language: {self.language}\n",
                f"decision: {task.intent_spec.decision}\n",
                f"response_intent: {task.intent_spec.response_intent}\n",
                f"will_help_now: {json.dumps(task.intent_spec.will_help_now)}\n",
                "Judge the candidate only. Do not rewrite it.\n",
                "Call the provided function with keys pass_verdict, score, issues, repair_instructions.\n",
                "Do not place JSON, belief, thinking, prose, or markdown in assistant text.\n",
                self._judge_rubric_block(),
                f"Input: {input_json}\n",
                f"Candidate: {candidate_json}\n",
                retry_block,
            ]
        )

    @staticmethod
    def _judge_rubric_block() -> str:
        return (
            "Checks: belief is first-person context; thinking is internal monologue; "
            "counterparty stays named; meaning stays aligned with response_intent; "
            "no invented scene details.\n"
            "Use pass_verdict=true only when the candidate is reliable overall.\n"
            "Keep issues and repair_instructions short and concrete.\n"
        )

    @staticmethod
    def _retry_feedback_block(retry_feedback: tuple[PolicyTextIssue, ...]) -> str:
        if not retry_feedback:
            return ""
        lines = ["Previous retry feedback to keep in mind: "]
        lines.append(" | ".join(issue.repair_instruction for issue in retry_feedback if issue.repair_instruction.strip()))
        lines.append("\n")
        return "".join(lines)

    @classmethod
    def _build_semantic_issues(cls, verdict: PolicyTextJudgeVerdict) -> list[PolicyTextIssue]:
        repair_items = [item.strip() for item in verdict.repair_instructions if item.strip()]
        issue_items = [item.strip() for item in verdict.issues if item.strip()]
        if not repair_items:
            repair_items = issue_items
        if not repair_items:
            repair_items = ["semantic judge rejected the output; rewrite it to satisfy the rubric"]
        if not issue_items:
            issue_items = repair_items
        built: list[PolicyTextIssue] = []
        for index, repair in enumerate(repair_items):
            issue_text = issue_items[index] if index < len(issue_items) else repair
            built.append(
                PolicyTextIssue(
                    code=cls._semantic_issue_code(f"{issue_text} {repair}"),
                    origin="semantic_judge",
                    field="combined",
                    message=issue_text,
                    repair_instruction=repair,
                )
            )
        return built

    @staticmethod
    def _semantic_issue_code(text: str) -> str:
        lowered = text.lower()
        if any(token in lowered for token in ("invented", "made up", "fabricated", "scene detail", "exact task", "exact details")):
            return "semantic_invented_details"
        if any(
            token in lowered
            for token in (
                "intent",
                "aligned",
                "alignment",
                "branch",
                "response_intent",
                "meaning",
                "not taking this on now",
                "taking this on now",
            )
        ):
            return "semantic_alignment"
        return "semantic_other"

    @classmethod
    def _tool_spec(cls) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": cls.TOOL_NAME,
                "description": "Submit the final semantic judgment for one policy_text candidate.",
                "parameters": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "pass_verdict": {
                            "type": "boolean",
                            "description": "Whether the candidate is reliable overall.",
                        },
                        "score": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 5,
                            "description": "Overall quality score from 0 to 5.",
                        },
                        "issues": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Short concrete problems found in the candidate.",
                        },
                        "repair_instructions": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Short concrete rewrite instructions for the next retry.",
                        },
                    },
                    "required": [
                        "pass_verdict",
                        "score",
                        "issues",
                        "repair_instructions",
                    ],
                },
            },
        }

def _preview_text(text: str, *, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
