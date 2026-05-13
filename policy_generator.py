"""Rule-based policy record generator with staged sampling.

Uses constrained staged sampling (not Cartesian product):
  1. sample a decision (quota-balanced)
  2. sample a relation bundle
  3. sample a state bundle
  4. sample cost/risk (scope-bounded)
  5. derive reason tags
  6. run consistency filters — reject and retry on implausible combos
"""

from __future__ import annotations

import logging
from typing import Optional

from entity_catalog import make_counterparty_identity
from policy_models import (
    DECISION_STRATEGY_MAP,
    DECISION_VALUES,
    POLICY_AXES,
    REASON_TAG_VALUES,
    RELATION_PROFILES,
    CostRiskSlice,
    PolicyDecision,
    PolicyRecord,
    RelationSlice,
    RequestContract,
    StateSlice,
    make_policy_record_id,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Consistency rules
# ---------------------------------------------------------------------------

def _check_consistency(record: PolicyRecord) -> list[str]:
    """Return list of consistency violations (empty = valid)."""
    issues: list[str] = []

    r = record.relation
    s = record.state
    p = record.policy

    # --- Relation-internal constraints ---

    # Stranger + high closeness is contradictory
    if r.relation_label in ("陌生人",) and r.relation_closeness == "high":
        issues.append("陌生人 with high closeness")

    # Family + low closeness is very unusual
    if r.relation_label in ("家人", "长辈") and r.relation_closeness == "low":
        issues.append("family label with low closeness")

    # High tension + positive reciprocity rarely co-occur
    if r.unfinished_tension == "high" and r.reciprocity_history == "positive":
        issues.append("high_tension with positive_reciprocity")

    # --- Relation ↔ Decision constraints ---

    # High obligation + minimal_acknowledgment is implausible without strong state pressure
    if (
        r.role_obligation == "high"
        and p.decision in ("minimal_acknowledgment", "decline")
        and s.time_pressure != "high"
        and s.energy != "low"
    ):
        issues.append("high_obligation declines without strong state pressure")

    # Close relation + decline is unusual without tension or bad history
    if (
        r.relation_closeness == "high"
        and p.decision in ("decline", "set_boundary")
        and r.unfinished_tension == "low"
        and r.reciprocity_history != "negative"
    ):
        issues.append("close_relation declines without tension or negative history")

    # --- State ↔ Decision constraints ---

    # Low energy + engage_now is plausible but should not dominate
    if s.energy == "low" and p.decision == "engage_now":
        issues.append("low_energy_engage_now")

    # High time_pressure + engage_now is fine
    # Low time_pressure + defer is unexpected
    if s.time_pressure == "low" and p.decision == "defer":
        issues.append("low_time_pressure_defer")

    # --- Trust ↔ Decision constraints ---

    # Low trust + engage_now is unusual
    if r.trust_in_target == "low" and p.decision == "engage_now":
        issues.append("low_trust_engage_now")

    return issues


# Stricter checks: combinations that should be outright rejected
def _is_implausible(record: PolicyRecord) -> bool:
    """Return True if the combination is implausible and should be rejected."""
    r = record.relation
    s = record.state
    p = record.policy

    # Family/close + set_boundary — social violation
    if (
        r.relation_label in ("家人", "长辈")
        and r.relation_closeness in ("medium", "high")
        and p.decision == "set_boundary"
    ):
        return True

    # Stranger + high obligation — nonsensical
    if r.relation_label == "陌生人" and r.role_obligation == "high":
        return True

    # High trust + high tension + positive reciprocity — inconsistent
    if (
        r.trust_in_target == "high"
        and r.unfinished_tension == "high"
        and r.reciprocity_history == "positive"
    ):
        return True

    # engage_now with low confidence is unusual but not impossible — allow it
    return False


# ---------------------------------------------------------------------------
# Staged samplers
# ---------------------------------------------------------------------------

def _sample_decision(rng, decision_quotas: dict[str, int]) -> str:
    """Pick a decision, preferring under-filled quotas."""
    available = [d for d in DECISION_VALUES if decision_quotas.get(d, 0) > 0]
    if not available:
        available = DECISION_VALUES
    return rng.choice(available)


def _sample_relation_bundle(rng, decision: str, profile: Optional[dict]) -> RelationSlice:
    """Sample a relation slice consistent with the given decision."""
    # Pick a relation profile or use the provided one
    if profile is None:
        rel = rng.choice(RELATION_PROFILES)
    else:
        rel = profile

    # Closeness: usually matching the profile's typical value, sometimes varied
    closeness = rng.choice(POLICY_AXES["relation_closeness"])
    # Bias toward the profile's typical closeness
    if rng.random() < 0.5:
        closeness = rel["typical_closeness"]

    # Trust: moderate correlation with closeness
    trust = rng.choice(POLICY_AXES["trust_in_target"])
    if closeness == "high" and rng.random() < 0.6:
        trust = rng.choice(["medium", "high"])
    elif closeness == "low" and rng.random() < 0.6:
        trust = rng.choice(["low", "medium"])

    # Obligation: depends on relation label
    high_obligation_labels = {"导师", "上司", "家人", "长辈", "客户", "老师"}
    low_obligation_labels = {"陌生人", "邻居"}
    if rel["label"] in high_obligation_labels:
        obligation = rng.choice(["medium", "high"])
    elif rel["label"] in low_obligation_labels:
        obligation = rng.choice(["low", "medium"])
    else:
        obligation = rng.choice(POLICY_AXES["role_obligation"])

    # Power: mostly determined by direction
    if rel["direction"] == "target_is_my_relation":
        # target is "my X" — depends on label
        if rel["label"] in ("上司", "导师", "长辈", "老师", "客户"):
            power = "target_higher"
        elif rel["label"] in ("下属", "学生", "晚辈"):
            power = "i_higher"
        else:
            power = rng.choice(["target_higher", "equal"])
    elif rel["direction"] == "i_am_targets_relation":
        if rel["label"] in ("上司", "导师", "长辈", "老师"):
            power = "i_higher"
        elif rel["label"] in ("下属", "学生", "晚辈"):
            power = "target_higher"
        else:
            power = rng.choice(["equal", "i_higher"])
    else:  # equal
        power = "equal"

    # Tension and reciprocity
    tension = rng.choice(POLICY_AXES["unfinished_tension"])
    reciprocity = rng.choice(POLICY_AXES["reciprocity_history"])

    # Adjust tension based on decision context
    if decision in ("decline", "set_boundary") and tension == "low":
        if rng.random() < 0.4:
            tension = rng.choice(["medium", "high"])

    return RelationSlice(
        relation_label=rel["label"],
        relation_direction=rel["direction"],
        relation_closeness=closeness,
        trust_in_target=trust,
        role_obligation=obligation,
        power_asymmetry=power,
        unfinished_tension=tension,
        reciprocity_history=reciprocity,
    )


def _sample_state_bundle(rng, decision: str) -> StateSlice:
    """Sample a state slice, with some influence from the decision."""
    # Energy: somewhat correlated with decision
    if decision in ("engage_now", "engage_briefly"):
        energy = rng.choice(["medium", "high"]) if rng.random() < 0.6 else rng.choice(POLICY_AXES["energy"])
    elif decision in ("decline", "minimal_acknowledgment"):
        energy = rng.choice(["low", "medium"]) if rng.random() < 0.5 else rng.choice(POLICY_AXES["energy"])
    else:
        energy = rng.choice(POLICY_AXES["energy"])

    # Time pressure
    if decision == "defer":
        time_pressure = rng.choice(["medium", "high"]) if rng.random() < 0.6 else rng.choice(POLICY_AXES["time_pressure"])
    else:
        time_pressure = rng.choice(POLICY_AXES["time_pressure"])

    # Cognitive clarity
    clarity = rng.choice(POLICY_AXES["cognitive_clarity"])

    # Emotional activation
    emotional = rng.choice(POLICY_AXES["emotional_activation"])

    # Social readiness
    social = rng.choice(POLICY_AXES["social_readiness"])
    if decision in ("engage_now", "engage_briefly"):
        if social == "guarded" and rng.random() < 0.4:
            social = rng.choice(["neutral", "open"])

    # Confidence
    confidence = rng.choice(POLICY_AXES["confidence_in_doing_the_action"])

    return StateSlice(
        energy=energy,
        time_pressure=time_pressure,
        cognitive_clarity=clarity,
        emotional_activation=emotional,
        social_readiness=social,
        confidence_in_doing_the_action=confidence,
    )


def _sample_cost_risk(rng) -> CostRiskSlice:
    """Cost and risk are always low per scope boundary."""
    return CostRiskSlice(
        local_cost="low",
        local_risk="low",
        expected_regret_if_declined=rng.choice(POLICY_AXES["expected_regret_if_declined"]),
    )


def _derive_reason_tags(record: PolicyRecord) -> list[str]:
    """Derive reason tags from the assembled record."""
    tags: list[str] = []
    r = record.relation
    s = record.state
    p = record.policy

    # Decision-derived
    if p.decision in ("defer",):
        tags.append("can_do_later")
    if p.decision in ("engage_now", "engage_briefly"):
        tags.append("can_do_now")

    # State-derived
    if s.time_pressure == "high":
        tags.append("time_pressure_high")
    elif s.time_pressure == "low":
        tags.append("time_pressure_low")

    if s.energy == "low":
        tags.append("energy_low")
    elif s.energy == "high":
        tags.append("energy_high")

    if s.social_readiness == "guarded":
        tags.append("socially_guarded")
    elif s.social_readiness == "open":
        tags.append("socially_ready")

    if s.cognitive_clarity in ("partial", "high"):
        tags.append("clarity_enables")
    else:
        tags.append("clarity_constrains")

    # Relation-derived
    if r.trust_in_target in ("medium", "high"):
        tags.append("trust_enables_engagement")
    else:
        tags.append("trust_constrains_engagement")

    if r.relation_closeness in ("medium", "high"):
        tags.append("closeness_enables_engagement")

    if r.unfinished_tension in ("medium", "high"):
        tags.append("tension_inhibits_engagement")

    # Obligation
    if r.role_obligation in ("medium", "high"):
        tags.append("obligation_preserved")
    else:
        tags.append("obligation_overridden")

    # Cost/risk
    tags.append("cost_acceptable")
    tags.append("risk_acceptable")

    # Regret
    if record.cost_risk.expected_regret_if_declined == "high":
        tags.append("regret_high")
    elif record.cost_risk.expected_regret_if_declined == "low":
        tags.append("regret_low")

    # Deduplicate while preserving order
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _pick_strategy(rng, decision: str) -> str:
    """Pick a strategy compatible with the decision."""
    strategies = DECISION_STRATEGY_MAP.get(decision, ["acknowledge_only"])
    return rng.choice(strategies)


# ---------------------------------------------------------------------------
# Policy sampler profile (for provenance)
# ---------------------------------------------------------------------------

class PolicySamplerProfile:
    """Tracks which sampling strategy was used for a record."""
    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return self.name


DEFAULT_PROFILE = PolicySamplerProfile("staged_v1")


# ---------------------------------------------------------------------------
# PolicyGenerator
# ---------------------------------------------------------------------------

class PolicyGenerator:
    """Generates policy records via staged sampling with consistency filters.

    Pure generation only; persistence is owned by the task runner.
    """

    MAX_CONSISTENCY_RETRIES = 20

    def __init__(
        self,
        seed: int = 42,
        profile: PolicySamplerProfile = DEFAULT_PROFILE,
        *,
        decision_weights: dict[str, float] | None = None,
    ):
        self.seed = seed
        self.profile = profile
        self.decision_weights = decision_weights or {}
        self._rng = None  # lazily initialized

    @property
    def rng(self):
        if self._rng is None:
            import random
            self._rng = random.Random(self.seed)
        return self._rng

    # -- Quota allocation --

    def _build_decision_quotas(self, count: int) -> dict[str, int]:
        """Allocate count across decisions, respecting optional weights.

        Each decision's floor is scaled by its weight (default 1.0).
        A weight of 3.0 for ``engage_now`` means it receives 3× the
        baseline floor, roughly tripling its share of the generated corpus.

        When weighted floors sum beyond *count*, non-weighted decisions are
        scaled down proportionally so the total never exceeds *count*.
        """
        n_decisions = len(DECISION_VALUES)
        base_floor = max(1, count // (n_decisions * 2))
        quotas: dict[str, int] = {}
        for d in DECISION_VALUES:
            w = self.decision_weights.get(d, 1.0)
            quotas[d] = max(1, int(base_floor * w))

        remaining = count - sum(quotas.values())
        if remaining > 0:
            # Distribute surplus across decisions, weighted by their multipliers
            total_weight = sum(self.decision_weights.get(d, 1.0) for d in DECISION_VALUES)
            weighted_remainder: dict[str, float] = {}
            for d in DECISION_VALUES:
                w = self.decision_weights.get(d, 1.0)
                weighted_remainder[d] = remaining * (w / total_weight)
            allocated = 0
            for d in DECISION_VALUES:
                quotas[d] += int(weighted_remainder[d])
                allocated += int(weighted_remainder[d])
            leftover = remaining - allocated
            ordered = sorted(DECISION_VALUES, key=lambda d: self.decision_weights.get(d, 1.0), reverse=True)
            for i in range(leftover):
                quotas[ordered[i % len(ordered)]] += 1
        elif remaining < 0:
            # Over-allocated: scale down non-weighted decisions proportionally.
            # Never shrink engage_now below its weighted floor.
            shortfall = -remaining
            other_decisions = [d for d in DECISION_VALUES if self.decision_weights.get(d, 1.0) <= 1.0]
            if other_decisions:
                other_total = sum(quotas[d] for d in other_decisions)
                if other_total > 0:
                    # Proportional reduction across other decisions, preserving at least 1 each
                    reduced = 0
                    for d in other_decisions:
                        if reduced >= shortfall:
                            break
                        share = int(shortfall * (quotas[d] / other_total))
                        share = min(share, quotas[d] - 1)  # keep at least 1
                        quotas[d] -= share
                        reduced += share
                    # If still short, take 1 from largest remaining others
                    remaining_shortfall = shortfall - reduced
                    others_by_size = sorted(other_decisions, key=lambda d: quotas[d], reverse=True)
                    for d in others_by_size:
                        if remaining_shortfall <= 0:
                            break
                        if quotas[d] > 1:
                            quotas[d] -= 1
                            remaining_shortfall -= 1

        return quotas

    def _build_relation_label_quotas(self, count: int) -> dict[str, int]:
        """Ensure minimum coverage across relation labels."""
        n_labels = len(RELATION_PROFILES)
        floor = max(1, count // (n_labels * 3))
        quotas: dict[str, int] = {}
        for rel in RELATION_PROFILES:
            quotas[rel["label"]] = floor
        remaining = count - sum(quotas.values())
        while remaining > 0:
            for rel in RELATION_PROFILES:
                if remaining <= 0:
                    break
                quotas[rel["label"]] += 1
                remaining -= 1
        return quotas

    # -- Main generation --

    def generate(self, count: int) -> list[PolicyRecord]:
        """Generate records until the run contains the first `count` canonical ids.

        In resume mode, we replay the deterministic generation stream from the
        beginning and only write missing ids. This keeps resumed runs aligned
        with a fresh run that uses the same seed and target count.
        """
        decision_quotas = self._build_decision_quotas(count)
        rel_quotas = self._build_relation_label_quotas(count)

        accepted_records: list[PolicyRecord] = []
        attempts = 0
        max_attempts = count * 3  # overall safety valve
        accepted_count = 0

        while accepted_count < count and attempts < max_attempts:
            attempts += 1
            index = accepted_count
            record_id = make_policy_record_id(index + 1)

            # Stage 1: pick decision (quota-aware)
            decision = _sample_decision(self.rng, decision_quotas)

            # Stage 2: pick relation profile (quota-aware)
            available_rels = [
                p for p in RELATION_PROFILES if rel_quotas.get(p["label"], 0) > 0
            ]
            if not available_rels:
                available_rels = RELATION_PROFILES
            chosen_rel = self.rng.choice(available_rels)

            relation = _sample_relation_bundle(self.rng, decision, chosen_rel)

            # Stage 3: state
            state = _sample_state_bundle(self.rng, decision)

            # Stage 4: cost/risk
            cost_risk = _sample_cost_risk(self.rng)

            # Stage 5: strategy
            strategy = _pick_strategy(self.rng, decision)

            # Assemble
            record = PolicyRecord(
                record_id=record_id,
                seed=self.seed,
                sampler_profile=self.profile.name,
                counterparty=make_counterparty_identity(record_id),
                request_contract=RequestContract(),
                relation=relation,
                state=state,
                cost_risk=cost_risk,
                policy=PolicyDecision(
                    decision=decision,
                    strategy=strategy,
                    reason_tags=[],  # filled after consistency check
                ),
            )

            # Stage 6: consistency filter
            if _is_implausible(record):
                continue

            issues = _check_consistency(record)
            # Allow records with minor issues, but limit how many
            if len(issues) > 2:
                continue

            # Derive reason tags after consistency check passes
            record.policy.reason_tags = _derive_reason_tags(record)

            # Stamp provenance
            record.stamp(
                record_id=record_id,
                seed=self.seed,
                profile=self.profile.name,
            )

            # Update quotas
            if decision_quotas.get(decision, 0) > 0:
                decision_quotas[decision] -= 1
            if rel_quotas.get(relation.relation_label, 0) > 0:
                rel_quotas[relation.relation_label] -= 1

            accepted_count += 1
            accepted_records.append(record)

        if accepted_count < count:
            raise RuntimeError(
                f"Unable to generate {count} policy records within {max_attempts} attempts "
                f"(accepted={accepted_count}, seed={self.seed}, profile={self.profile.name})"
            )

        logger.info(
            "Generated %d/%d policy records in %d attempts (seed=%d, profile=%s)",
            len(accepted_records), count, attempts, self.seed, self.profile.name,
        )
        return accepted_records
