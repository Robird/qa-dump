"""Shared typed contracts for policy-text and help-gate pipelines."""

from __future__ import annotations

from typing import Literal, get_args

LanguageCode = Literal["zh", "en"]
RelationKind = Literal[
    "mentor",
    "student",
    "coworker",
    "boss",
    "subordinate",
    "family",
    "friend",
    "stranger",
    "client",
    "partner",
    "neighbor",
    "classmate",
    "teacher",
    "junior",
    "elder",
    "other",
]
ResponseIntent = Literal[
    "help_now",
    "brief_non_help",
    "defer",
    "decline",
    "acknowledge_only",
    "set_boundary",
    "redirect",
]
PolicyDecisionName = Literal[
    "engage_now",
    "engage_briefly",
    "defer",
    "decline",
    "minimal_acknowledgment",
    "set_boundary",
    "redirect_channel_or_time",
]

LANGUAGE_VALUES: tuple[LanguageCode, ...] = get_args(LanguageCode)
RELATION_KIND_VALUES: tuple[RelationKind, ...] = get_args(RelationKind)
RESPONSE_INTENT_VALUES: tuple[ResponseIntent, ...] = get_args(ResponseIntent)
POLICY_DECISION_VALUES: tuple[PolicyDecisionName, ...] = get_args(PolicyDecisionName)
