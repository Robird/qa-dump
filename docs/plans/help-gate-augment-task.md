# HelpGateAugmentTask Plan

This document now defines `HelpGateAugmentTask` as a downstream QA-side projection task built on top of the generic policy layer described in [policy-layer-foundation.md](/repos/qa-dump/docs/plans/policy-layer-foundation.md).

It is no longer the place where the general decision ontology is defined.

Instead, it answers a narrower question:

- how should a reusable policy record be combined with QA payloads to create answer-gating training samples?


## 1. Goal

Use existing QA data as a payload source and combine it with policy-layer records so that the final sample teaches:

- when to answer now
- when not to answer now
- how that choice should be expressed immediately

In this task:

- the QA dataset provides question and answer content
- the policy layer provides state, relation, trust, obligation, and immediate decision
- the projection layer combines them into trainable agentic samples


## 2. Dependency on the Policy Layer

This task should inherit its decision logic from the generic policy layer.

That means the QA task should not redefine:

- relation semantics
- trust semantics
- obligation semantics
- state axes
- generic decision labels

Instead, it should consume policy records that already satisfy the shared scope boundary:

- the requested action is doable now
- the requested action is low-cost but not zero-cost
- the requested action is formally permissible

For QA, that means:

- answering is treated as one payload-specific realization of a generic request to act


## 3. Why QA Is Still a Good First Payload Adapter

QA is a strong first adapter because:

- the payload is already large and structured
- the "fulfillment content" is already available as a source answer
- answer quality can be checked against an existing authority
- the contrast between "engage now" and "do not engage now" is easy to inspect

This makes QA a practical first proving ground for the policy layer even though the foundation is not QA-specific.


## 4. Payload Adapter Contract for QA

A QA adapter should extract at least:

- `payload_type = question`
- `request_text = question`
- `fulfillment_content = answer`
- `topic_metadata`
- optional `bloom_level`

Suggested minimal payload record:

```json
{
  "payload_type": "question",
  "derived_from_question_id": "...",
  "request_text": "哥特式建筑起源于哪个时期？",
  "fulfillment_content": "哥特式建筑起源于12世纪中叶的法国...",
  "domain_slug": "人文艺术",
  "node_path": "architecture/architectural_design/architectural_style_and_history",
  "bloom_level": "remember"
}
```


## 5. Policy-to-QA Mapping

When a generic policy record is attached to a QA payload, the projection should map generic decisions into QA-side outcomes.

Useful QA-side interpretations:

- `engage_now` -> answer seriously now
- `engage_briefly` -> answer only briefly or partially
- `defer` -> do not answer seriously now, but keep the channel open
- `defer_with_hint` -> delay and give a time or condition hint
- `decline` -> do not answer now and do not promise fulfillment
- `set_boundary` -> refuse in a boundary-preserving way
- `minimal_acknowledgment` -> acknowledge without real answering
- `redirect_channel_or_time` -> ask to move the answer to another context

This mapping is a projection rule, not the canonical semantic truth.


## 6. Final Sample Pattern

The composed QA sample should follow this pattern:

1. a question payload is provided
2. a policy record is attached
3. the sample is projected into `observation / belief / me`
4. the final text or structured target is realized

This makes the QA answer only one possible outcome of the policy decision rather than an always-on default.


## 7. Recommended Semantic Composition Record

Suggested composed record:

```json
{
  "task_family": "answer_gate_augment",
  "policy_record_id": "...",
  "payload": {
    "payload_type": "question",
    "derived_from_question_id": "...",
    "request_text": "...",
    "fulfillment_content": "..."
  },
  "policy": {
    "decision": "defer",
    "strategy": "defer_with_time_hint",
    "reason_tags": [
      "time_pressure_high",
      "can_do_later"
    ]
  },
  "projection": {
    "qa_outcome": "not_answer_now",
    "should_include_fulfillment_content": false
  }
}
```

For an `engage_now` sample, `should_include_fulfillment_content` would normally be true.


## 8. Text Projection Guidance

This task should not rely on naive prompt stitching such as:

- question text
- plus one paragraph of relation text
- plus one paragraph of state text
- plus a direct answer or refusal

That style is easy to generate but often weak as training data because the payload tends to dominate the policy signal.

Preferred projection pattern:

- `observation`: the incoming question
- `belief`: compact relation and state slice from the policy layer
- `me`: decision, short rationale, response

This keeps the policy information salient without burying it in uncontrolled prose.


## 9. Handling the Answer Content

When the policy projection implies serious engagement now, the source QA answer should remain the knowledge authority.

Allowed operations:

- use the source answer directly
- lightly rewrite for tone or brevity
- shorten for `engage_briefly`

Disallowed behavior:

- major factual drift
- relation- or mood-driven corruption of knowledge
- inventing a different answer because the social scene changed

Important principle:

- policy changes delivery and willingness
- it should not silently mutate domain truth


## 10. Handling Non-Answer Outcomes

When the policy projection implies non-engagement now, the final response should match the chosen strategy without accidentally containing a full answer.

Useful strategy realizations include:

- polite defer
- defer with a later-time hint
- brief acknowledgment only
- boundary-setting refusal
- channel shift
- minimal brush-off

This task should still keep intentional false answering out of scope.


## 11. Sampling Design

The projection task should combine:

- sampled QA payloads
- sampled policy records

Recommended balancing:

- mix easy and hard QA payloads
- cover both close and distant relations
- cover high-trust and low-trust cases
- cover calm and strained states
- cover both engage and non-engage outcomes

Important anti-collapse rule:

- do not let QA difficulty alone determine whether the agent answers now

The policy layer should remain the main driver of the immediate decision.


## 12. Compatibility Checks

Before composition, each QA payload and policy record should pass compatibility checks.

Examples:

- the policy record's scope boundary still fits a QA answer action
- the strategy does not imply impossible behavior
- the emotional or trust setting does not demand out-of-scope complexity
- the projected response style is plausible for the relation slice


## 13. Validation Rules

Minimum validation:

- the payload comes from a valid QA source item
- the policy record is valid under the shared policy schema
- QA-side outcome matches the generic decision
- if `engage_now`, the answer stays aligned with source truth
- if not engaging now, the response does not leak a detailed answer

Nice-to-have validation:

- answer similarity checks for engage cases
- lexical dedup checks for refusal and defer templates
- sample teacher review on projection quality


## 14. Output Modes

This task should export:

1. semantic composition record
2. `observation / belief / me` projection
3. human-readable text projection

The semantic composition record should remain canonical.


## 15. Recommended First Version

1. reuse policy records from `PolicyLayerFoundation`
2. use `ds-2` as the first and only payload source
3. support `engage_now`, `defer`, `decline`, and `minimal_acknowledgment` first
4. preserve source answers as authority for engage cases
5. keep non-answer responses short and strategy-faithful

This gives us a clean first end-to-end test of:

- reusable policy layer
- payload adapter design
- controlled text projection


## 16. Open Questions

- should `engage_briefly` be included in v1 or added after basic engage/defer/decline works?
- should some QA payloads be filtered out because the answer would be too long for this projection style?
- should we export both terse and richer `belief` projections for ablation?


## 17. Success Criteria

This task is successful if:

- the same QA payload can be combined with multiple policy records cleanly
- policy signals remain visible after projection into text
- engage cases preserve answer correctness
- non-engage cases feel realistic and varied
- the task demonstrates that QA can be treated as a payload adapter rather than the core decision ontology
