"""Attempt-loop orchestration for policy_text generation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from policy_text_generator import PolicyTextGenerator, PolicyTextRuleValidationError
from policy_text_issues import PolicyTextIssue
from policy_text_judge import PolicyTextSemanticJudge, PolicyTextSemanticRejection
from policy_text_models import PolicyTextRealization
from policy_text_preparation import PreparedPolicyTextTask

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolicyTextRealizationOutcome:
    realization: PolicyTextRealization | None
    attempts_used: int
    judge_rejections: int
    last_error: Exception | None


class PolicyTextRealizer:
    def __init__(
        self,
        generator: PolicyTextGenerator,
        *,
        semantic_judge: PolicyTextSemanticJudge,
    ):
        self.generator = generator
        self.semantic_judge = semantic_judge

    def realize(
        self,
        task: PreparedPolicyTextTask,
        *,
        max_attempts: int,
    ) -> PolicyTextRealizationOutcome:
        last_error: Exception | None = None
        retry_feedback: tuple[PolicyTextIssue, ...] = ()
        judge_rejections = 0

        for attempt in range(1, max_attempts + 1):
            logger.info(
                "Realizing %s (attempt=%d/%d, will_help_now=%s, response_intent=%s)",
                task.source_policy.record_id,
                attempt,
                max_attempts,
                task.intent_spec.will_help_now,
                task.intent_spec.response_intent,
            )
            try:
                realization = self.generator.generate(
                    task,
                    retry_feedback=retry_feedback,
                )
                self.semantic_judge.evaluate(
                    task=task,
                    realization=realization,
                    retry_feedback=retry_feedback,
                )
                return PolicyTextRealizationOutcome(
                    realization=realization,
                    attempts_used=attempt,
                    judge_rejections=judge_rejections,
                    last_error=None,
                )
            except PolicyTextSemanticRejection as exc:
                last_error = exc
                retry_feedback = exc.issues
                judge_rejections += 1
                logger.info(
                    "Semantic judge rejected %s on attempt %d with feedback: %s",
                    task.source_policy.record_id,
                    attempt,
                    [issue.message for issue in retry_feedback],
                )
            except PolicyTextRuleValidationError as exc:
                last_error = exc
                retry_feedback = exc.issues
                logger.info(
                    "Rule validation rejected %s on attempt %d with issues: %s",
                    task.source_policy.record_id,
                    attempt,
                    [issue.message for issue in retry_feedback],
                )
            except Exception as exc:
                last_error = exc
            logger.warning(
                "Policy text realization failed for %s on attempt %d/%d: %s",
                task.source_policy.record_id,
                attempt,
                max_attempts,
                last_error,
            )

        return PolicyTextRealizationOutcome(
            realization=None,
            attempts_used=max_attempts,
            judge_rejections=judge_rejections,
            last_error=last_error,
        )
