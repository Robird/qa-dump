"""Canonical policy-layer Pydantic models.

Payload-agnostic semantic truth for policy records as described in
docs/plans/policy-layer-foundation.md.  These models are reusable across
QA, help, trust, compliance, and other future payload families.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from entity_catalog import CounterpartyIdentity, make_counterparty_identity, validate_counterparty_identity
from relation_catalog import POLICY_RELATION_PROFILES


POLICY_SCHEMA_VERSION = "1.1"
POLICY_GENERATOR_VERSION = "1.1"


# ---------------------------------------------------------------------------
# Value enumerations (as module-level lists — not Enums — for sampling ease)
# ---------------------------------------------------------------------------

DECISION_VALUES: list[str] = [
    "engage_now",
    "engage_briefly",
    "defer",
    "decline",
    "minimal_acknowledgment",
    "set_boundary",
    "redirect_channel_or_time",
]

STRATEGY_VALUES: list[str] = [
    "answer_seriously",
    "answer_briefly",
    "defer_with_time_hint",
    "defer_with_hint",
    "acknowledge_only",
    "polite_decline",
    "set_boundary",
    "redirect_channel_or_time",
]

REASON_TAG_VALUES: list[str] = [
    "time_pressure_high",
    "time_pressure_low",
    "energy_low",
    "energy_high",
    "can_do_later",
    "can_do_now",
    "obligation_preserved",
    "obligation_overridden",
    "trust_enables_engagement",
    "trust_constrains_engagement",
    "closeness_enables_engagement",
    "tension_inhibits_engagement",
    "cost_acceptable",
    "risk_acceptable",
    "regret_high",
    "regret_low",
    "socially_ready",
    "socially_guarded",
    "clarity_enables",
    "clarity_constrains",
]


# ---------------------------------------------------------------------------
# Semantic slices
# ---------------------------------------------------------------------------

class RelationSlice(BaseModel):
    relation_label: str = ""
    relation_direction: str = ""       # "target_is_my_relation" | "i_am_targets_relation" | "equal"
    relation_closeness: str = ""       # "low" | "medium" | "high"
    trust_in_target: str = ""          # "low" | "medium" | "high"
    role_obligation: str = ""          # "low" | "medium" | "high"
    power_asymmetry: str = ""          # "target_higher" | "equal" | "i_higher"
    unfinished_tension: str = ""       # "low" | "medium" | "high"
    reciprocity_history: str = ""      # "negative" | "neutral" | "positive"


class StateSlice(BaseModel):
    energy: str = ""                   # "low" | "medium" | "high"
    time_pressure: str = ""            # "low" | "medium" | "high"
    cognitive_clarity: str = ""        # "low" | "partial" | "high"
    emotional_activation: str = ""     # "low" | "medium" | "high"
    social_readiness: str = ""         # "guarded" | "neutral" | "open"
    confidence_in_doing_the_action: str = ""  # "low" | "medium" | "high"


class CostRiskSlice(BaseModel):
    local_cost: str = ""               # "low" (scope boundary)
    local_risk: str = ""               # "low" (scope boundary)
    expected_regret_if_declined: str = ""  # "low" | "medium" | "high"


class RequestContract(BaseModel):
    is_doable_now: bool = True
    is_low_cost_nonzero: bool = True
    is_formally_permissible: bool = True


class PolicyDecision(BaseModel):
    decision: str = ""
    strategy: str = ""
    reason_tags: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Canonical policy record
# ---------------------------------------------------------------------------

class PolicyRecord(BaseModel):
    # Provenance
    schema_version: str = POLICY_SCHEMA_VERSION
    generator_version: str = POLICY_GENERATOR_VERSION
    record_id: str = ""
    task_family: str = "policy_layer_foundation"
    seed: int = 0
    sampler_profile: str = ""
    created_at: str = ""

    # Record-local entity anchor
    counterparty: CounterpartyIdentity

    # Scope contract
    request_contract: RequestContract = Field(default_factory=RequestContract)

    # Semantic slices
    relation: RelationSlice = Field(default_factory=RelationSlice)
    state: StateSlice = Field(default_factory=StateSlice)
    cost_risk: CostRiskSlice = Field(default_factory=CostRiskSlice)
    policy: PolicyDecision = Field(default_factory=PolicyDecision)

    @model_validator(mode="after")
    def _validate_policy_record_contract(self) -> "PolicyRecord":
        if self.schema_version != POLICY_SCHEMA_VERSION:
            raise ValueError(
                f"policy schema_version {self.schema_version!r} does not match expected {POLICY_SCHEMA_VERSION!r}"
            )
        if self.generator_version != POLICY_GENERATOR_VERSION:
            raise ValueError(
                "policy generator_version "
                f"{self.generator_version!r} does not match expected {POLICY_GENERATOR_VERSION!r}"
            )
        if not self.record_id:
            raise ValueError("policy record_id is required")
        validate_counterparty_identity(self.counterparty, expected_record_id=self.record_id)
        return self

    def stamp(self, record_id: str, seed: int, profile: str) -> None:
        self.record_id = record_id
        self.seed = seed
        self.sampler_profile = profile
        self.counterparty = make_counterparty_identity(record_id)


# ---------------------------------------------------------------------------
# Axis value inventory for samplers
# ---------------------------------------------------------------------------

POLICY_AXES: dict[str, list[str]] = {
    "relation_closeness": ["low", "medium", "high"],
    "trust_in_target": ["low", "medium", "high"],
    "role_obligation": ["low", "medium", "high"],
    "power_asymmetry": ["target_higher", "equal", "i_higher"],
    "unfinished_tension": ["low", "medium", "high"],
    "reciprocity_history": ["negative", "neutral", "positive"],
    "energy": ["low", "medium", "high"],
    "time_pressure": ["low", "medium", "high"],
    "cognitive_clarity": ["low", "partial", "high"],
    "emotional_activation": ["low", "medium", "high"],
    "social_readiness": ["guarded", "neutral", "open"],
    "confidence_in_doing_the_action": ["low", "medium", "high"],
    "local_cost": ["low"],
    "local_risk": ["low"],
    "expected_regret_if_declined": ["low", "medium", "high"],
}

# Decision → valid strategies mapping
DECISION_STRATEGY_MAP: dict[str, list[str]] = {
    "engage_now": ["answer_seriously"],
    "engage_briefly": ["answer_briefly"],
    "defer": ["defer_with_time_hint", "defer_with_hint"],
    "decline": ["polite_decline", "set_boundary"],
    "minimal_acknowledgment": ["acknowledge_only"],
    "set_boundary": ["set_boundary"],
    "redirect_channel_or_time": ["redirect_channel_or_time"],
}

# Valid relation labels with direction and closeness hints
# (label, direction, typical_closeness)
RELATION_PROFILES: list[dict] = [profile.copy() for profile in POLICY_RELATION_PROFILES]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_policy_record_id(index: int) -> str:
    return f"policy_rec__{index:06d}"


def validate_policy_record(
    raw: dict | PolicyRecord,
    *,
    expected_record_id: str | None = None,
) -> PolicyRecord:
    record = PolicyRecord.model_validate(
        raw.model_dump() if isinstance(raw, PolicyRecord) else raw
    )
    if expected_record_id is not None and record.record_id != expected_record_id:
        raise ValueError(
            f"policy record_id {record.record_id!r} does not match item key {expected_record_id!r}"
        )
    return record
