"""Preparation helpers for policy_text generation."""

from __future__ import annotations

from dataclasses import dataclass

from entity_catalog import CounterpartyMention, counterparty_mention_for
from policy_models import PolicyRecord
from policy_text_models import (
    IntentSpec,
    PolicyTextDecisionInput,
    PolicyTextRealization,
    PolicyTextRealizationInput,
    PolicyTextRecord,
    PolicyTextRelationInput,
    PolicyTextRequestContextInput,
    PolicyTextStateInput,
    TEXT_SCHEMA_VERSION,
    intent_spec_from_decision,
    make_policy_text_record_id,
    validate_policy_text_record,
)
from relation_catalog import canonical_relation_kind


HIGH_SIGNAL_REASON_TAGS: tuple[str, ...] = (
    "time_pressure_high",
    "energy_low",
    "energy_high",
    "can_do_later",
    "can_do_now",
    "trust_constrains_engagement",
    "trust_enables_engagement",
    "closeness_enables_engagement",
    "tension_inhibits_engagement",
    "regret_high",
    "socially_guarded",
    "socially_ready",
    "clarity_constrains",
    "clarity_enables",
)


@dataclass(frozen=True)
class PreparedPolicyTextTask:
    source_policy: PolicyRecord
    language: str
    item_key: str
    intent_spec: IntentSpec
    relation_kind: str
    counterparty_mention: CounterpartyMention
    realization_input: PolicyTextRealizationInput


def select_reason_tags(policy_record: PolicyRecord) -> list[str]:
    selected = [tag for tag in policy_record.policy.reason_tags if tag in HIGH_SIGNAL_REASON_TAGS]
    if not selected:
        selected = [
            tag for tag in policy_record.policy.reason_tags if tag not in {"cost_acceptable", "risk_acceptable"}
        ]
    return selected[:4]


def project_policy_record_for_text(
    policy_record: PolicyRecord,
    *,
    intent_spec: IntentSpec,
) -> PolicyTextRealizationInput:
    relation_kind = canonical_relation_kind(policy_record.relation.relation_label)
    counterparty_mention = counterparty_mention_for(policy_record.counterparty, relation_kind)
    return PolicyTextRealizationInput(
        counterparty_mention=counterparty_mention,
        relation=PolicyTextRelationInput(
            label=policy_record.relation.relation_label,
            closeness=policy_record.relation.relation_closeness,
            trust=policy_record.relation.trust_in_target,
            obligation=policy_record.relation.role_obligation,
            tension=policy_record.relation.unfinished_tension,
            reciprocity=policy_record.relation.reciprocity_history,
            power=policy_record.relation.power_asymmetry,
        ),
        state=PolicyTextStateInput(
            energy=policy_record.state.energy,
            time_pressure=policy_record.state.time_pressure,
            clarity=policy_record.state.cognitive_clarity,
            emotional_activation=policy_record.state.emotional_activation,
            social_readiness=policy_record.state.social_readiness,
            confidence=policy_record.state.confidence_in_doing_the_action,
        ),
        request_context=PolicyTextRequestContextInput(
            is_doable_now=policy_record.request_contract.is_doable_now,
        ),
        decision=PolicyTextDecisionInput(
            will_help_now=intent_spec.will_help_now,
            response_intent=intent_spec.response_intent,
            policy_decision=policy_record.policy.decision,
            policy_strategy=policy_record.policy.strategy,
        ),
        reason_tags=select_reason_tags(policy_record),
    )


def prepare_policy_text_task(
    source_policy: PolicyRecord,
    *,
    language: str,
) -> PreparedPolicyTextTask:
    intent_spec = intent_spec_from_decision(source_policy.policy.decision)
    relation_kind = canonical_relation_kind(source_policy.relation.relation_label)
    realization_input = project_policy_record_for_text(source_policy, intent_spec=intent_spec)
    return PreparedPolicyTextTask(
        source_policy=source_policy,
        language=language,
        item_key=make_policy_text_record_id(source_policy.record_id),
        intent_spec=intent_spec,
        relation_kind=relation_kind,
        counterparty_mention=realization_input.counterparty_mention,
        realization_input=realization_input,
    )


def build_policy_text_record(
    task: PreparedPolicyTextTask,
    realization: PolicyTextRealization,
) -> PolicyTextRecord:
    return validate_policy_text_record(
        PolicyTextRecord(
            schema_version=TEXT_SCHEMA_VERSION,
            record_id=task.item_key,
            language=task.language,
            source_policy_record_id=task.source_policy.record_id,
            relation_kind=task.relation_kind,
            policy_decision=task.source_policy.policy.decision,
            belief=realization.belief.strip(),
            thinking=realization.thinking.strip(),
        ),
        expected_item_key=task.item_key,
    )


def validate_policy_text_record_against_source(
    record: PolicyTextRecord,
    source_policy: PolicyRecord,
) -> None:
    if record.source_policy_record_id != source_policy.record_id:
        raise ValueError("policy_text source_policy_record_id does not match source policy record_id")
    expected_relation_kind = canonical_relation_kind(source_policy.relation.relation_label)
    if record.relation_kind != expected_relation_kind:
        raise ValueError("policy_text relation_kind does not match source policy relation label")
    if record.policy_decision != source_policy.policy.decision:
        raise ValueError("policy_text policy_decision does not match source policy decision")
