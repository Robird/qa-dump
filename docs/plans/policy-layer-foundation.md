# PolicyLayerFoundation Plan

This document defines a generic policy layer that is intentionally decoupled from any one payload family such as QA, help requests, trust judgments, or compliance scenes.

The main idea is:

- first model whether and how the agent is willing to engage with a requested action
- later combine that policy layer with different payload-side datasets
- only at the final stage project the combined semantic record into training text


## 1. Goal

Build a reusable semantic policy layer that captures:

- current state
- relationship to the other party
- trust and obligation structure
- local cost and risk
- willingness to act now
- immediate response strategy

This layer should be reusable across multiple downstream scenarios rather than being tied to QA from the start.


## 2. Scope Boundary

The first version should deliberately avoid the full generality of all human action decisions.

Instead, it should focus on requests whose target action is:

- within the agent's capability
- possible to do immediately
- low-cost but not zero-cost
- formally permissible

This scope boundary is very important.

It excludes many harder factors:

- inability or missing skill
- long-horizon planning
- expensive sacrifice
- clearly illegal or clearly prohibited behavior
- multi-step tool use
- deception-heavy cases

This keeps the task focused on one meaningful decision quadrant:

- "I can do this now, and it is allowed, but I still may or may not choose to do it."


## 3. Why This Abstraction Is Better Than QA-First Design

If we build around QA too early, we risk mixing three separable things:

- the content payload
- the policy decision
- the text surface form

That makes reuse harder and creates avoidable confusion.

By separating the policy layer first:

- QA can later act as one payload adapter
- help / not-help can reuse the same policy dimensions
- trust / not-trust can reuse much of the same relation and state logic
- text projection can be redesigned without changing the semantic truth layer


## 4. Core Decision Question

Under the scope boundary above, the core question becomes:

- given a request for a doable, immediate, low-cost, permissible action, should I engage now, delay, limit, or decline?

This is the central object of supervision.

We are not yet modeling the entire action itself.

We are modeling the decision policy around the action.


## 5. Policy Axes

The policy layer should not collapse into a single `yes/no`.

Useful semantic axes include:

- `relation_closeness`
- `trust_in_target`
- `target_reliability`
- `role_obligation`
- `power_asymmetry`
- `unfinished_tension`
- `reciprocity_history`
- `current_energy`
- `current_time_pressure`
- `current_cognitive_clarity`
- `current_emotional_activation`
- `social_readiness`
- `local_cost`
- `local_risk`
- `expected_regret_if_declined`

These axes should be treated as semi-independent.

Important example:

- someone can be close but not trusted
- someone can be distant but still invoke strong obligation
- someone can be trusted but met at a bad moment


## 6. Relationship Modeling

Relationship should not be represented as only one kinship or role label.

Recommended relation slice:

- `relation_label`
- `relation_direction`
- `relation_closeness`
- `trust_in_target`
- `role_obligation`
- `power_asymmetry`
- `unfinished_tension`
- `reciprocity_history`

It is still useful to preserve directional surface diversity, for example:

- `<target>是我的<关系称谓>`
- `我是<target>的<关系称谓>`

But that surface diversity belongs to projection and realization.

At the semantic layer, the important thing is to preserve the underlying relation state.


## 7. State Modeling

The state layer should stay compact in v1.

Recommended first-pass fields:

- `energy`
- `time_pressure`
- `cognitive_clarity`
- `emotional_activation`
- `social_readiness`
- `confidence_in_doing_the_action`

We should not over-build a huge state machine here.

The goal is not full psychological realism yet.

The goal is to represent enough local state to explain why the same request may receive different immediate policies.


## 8. Decision Outputs

At the policy layer, avoid payload-specific labels like `answer_now` in the canonical schema.

Prefer generic action-policy outcomes such as:

- `engage_now`
- `engage_briefly`
- `defer`
- `defer_with_hint`
- `decline`
- `set_boundary`
- `minimal_acknowledgment`
- `redirect_channel_or_time`

These outputs are abstract enough to transfer across payload types.


## 9. Strategy vs Decision

It is useful to separate:

- `decision`
- `strategy`

Example:

- `decision = defer`
- `strategy = defer_with_time_hint`

Or:

- `decision = decline`
- `strategy = set_boundary`

This improves reuse and makes the response style less entangled with the underlying policy choice.


## 10. Canonical Semantic Schema

Suggested v1 record:

```json
{
  "task_family": "policy_layer_foundation",
  "request_contract": {
    "is_doable_now": true,
    "is_low_cost_nonzero": true,
    "is_formally_permissible": true
  },
  "relation": {
    "relation_label": "导师",
    "relation_direction": "target_is_my_relation",
    "relation_closeness": "medium",
    "trust_in_target": "high",
    "role_obligation": "high",
    "power_asymmetry": "target_higher",
    "unfinished_tension": "low",
    "reciprocity_history": "positive"
  },
  "state": {
    "energy": "low",
    "time_pressure": "high",
    "cognitive_clarity": "partial",
    "emotional_activation": "low",
    "social_readiness": "guarded",
    "confidence_in_doing_the_action": "high"
  },
  "cost_risk": {
    "local_cost": "low",
    "local_risk": "low",
    "expected_regret_if_declined": "medium"
  },
  "policy": {
    "decision": "defer",
    "strategy": "defer_with_time_hint",
    "reason_tags": [
      "time_pressure_high",
      "can_do_later",
      "obligation_preserved"
    ]
  }
}
```

This schema should be treated as semantic truth, not as a prompt template.


## 11. Payload Decoupling

The policy layer should not require a concrete payload in order to exist.

Instead, downstream tasks can attach payloads later.

Examples:

- QA question and answer pair
- help request scene
- claim to evaluate for trust
- small favor request
- invitation or interruption

This means we can generate policy records first, then combine them with payload datasets through adapters.


## 12. Payload Adapter Contract

Each downstream payload family should provide a thin adapter that maps its source data into a generic request slot.

A payload adapter may provide:

- `payload_type`
- `request_text`
- optional `fulfillment_content`
- optional `risk_hint`
- optional `domain_or_topic`

For QA:

- `request_text` is the user's question
- `fulfillment_content` is the source answer

For a help-request dataset:

- `request_text` is the favor or request
- `fulfillment_content` may be omitted or replaced by a short compliant action stub


## 13. Text Projection Is the Hard Part

The main technical difficulty is not the semantic policy design itself.

The hard part is controlled text fusion:

- policy variables are structured
- payload data is often already textual
- the final training sample must feel natural rather than templated
- but it must not lose or distort the semantic control variables

If we fuse too early by naive string concatenation, several failures become likely:

- the model ignores state and relation text
- the payload text dominates the sample
- relation and state leak into factual content
- the same semantics gets overfit to one wording pattern


## 14. Recommended Projection Pipeline

To manage that difficulty, use three layers.

### Layer A: semantic truth

Store:

- policy record
- payload record
- combination metadata

This is canonical.

### Layer B: protocol projection

Project the semantic record into a structured training shape such as:

- `observation`
- `belief`
- `me`

This layer decides what information belongs where.

### Layer C: surface realization

Render the structured projection into text or semi-structured target format.

This layer should vary wording while preserving upstream semantics.


## 15. Recommended Information Placement

A useful default projection is:

- `observation`: the request text and immediate scene signal
- `belief`: state slice, relation slice, local obligation, local cost
- `me`: decision, short rationale, immediate response strategy

Important principle:

- do not hide policy truth only inside prose
- keep structured fields available even if a text projection is also exported


## 16. Composition With Side Datasets

The policy layer should later combine with side datasets through controlled random composition.

Recommended composition process:

1. sample a policy record
2. sample a payload record from a compatible dataset
3. run a compatibility check
4. generate a protocol projection
5. realize text
6. validate that the final text still matches the semantic record

Compatibility checks may include:

- topic sensitivity constraints
- risk mismatch constraints
- trust mismatch constraints
- whether the payload naturally fits "doable now, low-cost, permissible"


## 17. Generation Strategy

This layer is well-suited to mixed automation.

### Rule-based parts

Use rules for:

- coverage balancing
- axis quotas
- compatibility constraints
- contradiction prevention
- combination sampling

### LLM-based parts

Use an LLM for:

- natural relation phrasing
- short state snippets
- brief rationale phrasing
- final response wording
- text-side diversity without changing semantic truth


## 18. Validation Rules

Minimum validation:

- request contract fields satisfy the intended scope boundary
- decision and strategy are compatible
- relation and state plausibly support the reason tags
- local cost remains low but nonzero
- final projection preserves semantic labels

Projection validation:

- relation wording matches relation direction
- state wording matches structured state fields
- final response reflects the chosen strategy
- no projection accidentally introduces out-of-scope complexity


## 19. Recommended First Implementation

1. define the canonical policy schema
2. build a sampler for relation, trust, obligation, and state axes
3. generate policy-only records first
4. export them in semantic and protocol-ready forms
5. only then attach a first payload adapter such as QA
6. treat answer-gating as one downstream projection task rather than the foundation itself


## 20. Open Questions

- should reason tags stay discrete, or should some be grouped into higher-level policy motives?
- how rich should reciprocity and tension history be in v1?
- should policy-only records ever be used directly for training before payload composition?
- how much wording diversity is enough before projection starts to blur semantic control?


## 21. Success Criteria

This foundation is successful if:

- policy records are reusable across more than one payload family
- the scope boundary remains clean and controllable
- text projections preserve policy semantics rather than washing them out
- downstream tasks can combine payload datasets with policy records by adapter rather than by redesign
- the project gains a true reusable decision layer rather than a QA-specific augmentation trick
