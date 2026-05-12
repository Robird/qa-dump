"""Shared issue types for policy_text generation, validation, and judging."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Literal


PolicyTextIssueCode = Literal[
    "belief_empty",
    "thinking_empty",
    "missing_counterparty_name",
    "belief_too_long",
    "thinking_too_long",
    "schema_jargon",
    "belief_not_first_person",
    "counterparty_direct_address",
    "counterparty_pronoun",
    "counterparty_generic_placeholder",
    "intent_immediate_help_mismatch",
    "intent_missing_cue",
    "intent_conflicting_cue",
    "semantic_alignment",
    "semantic_invented_details",
    "semantic_other",
]

PolicyTextIssueOrigin = Literal["rule_validator", "semantic_judge"]
PolicyTextIssueField = Literal["belief", "thinking", "combined"]


@dataclass(frozen=True)
class PolicyTextIssue:
    code: PolicyTextIssueCode
    origin: PolicyTextIssueOrigin
    message: str
    repair_instruction: str
    field: PolicyTextIssueField | None = None
    details: dict[str, str | bool] = dataclass_field(default_factory=dict)


def summarize_issue_messages(issues: tuple[PolicyTextIssue, ...]) -> str:
    return "; ".join(issue.message for issue in issues)


def retry_feedback_needs_name_repetition(issues: tuple[PolicyTextIssue, ...]) -> bool:
    return any(
        issue.code in {
            "missing_counterparty_name",
            "counterparty_pronoun",
            "counterparty_generic_placeholder",
        }
        for issue in issues
    )
