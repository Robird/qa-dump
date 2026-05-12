# PolicyTextRecordsTask Plan

This document defines a new derived-data task that turns structured
`policy_records` into language-specific text realizations suitable for later
composition with QA payloads.


## 1. Goal

Create a text-bearing policy dataset where each item includes:

- canonical structured policy fields for machine use
- a first-person `belief` text that describes the agent's known situation
- a short `thinking` text that states a visible reason and conclusion
- a binary control field `will_help_now`
- a structured `response_intent` field

The immediate downstream use is not direct answering.

It is to later compose:

- request-like QA payloads
- policy-layer social state
- compact belief context
- a visible "help now or not" decision signal

into richer training samples.


## 2. Why A Separate Derived Layer

This task should create a new first-class run rather than modifying
`policy_records` in place.

Recommended reason:

- `policy_records` is semantic truth
- `policy_text_records` is language-specific realization

Keeping them separate gives us:

- lower coupling between semantics and surface text
- easier iteration on prompts and style variation
- freedom to regenerate text without disturbing structured truth
- room for multiple realizations per source record in later versions

This is especially useful because text realization is the unstable part while
the structured policy layer is the stable control surface.


## 3. Task Boundary

### Upstream

- source run: `policy_records`
- source item: one structured policy record

### Downstream

- later composition with QA payloads or other help-request payloads
- training samples where `belief` becomes model input context
- non-tool-call branch control through `will_help_now == false`

This task does not yet combine with QA.

It only textualizes the policy layer into a reusable intermediate dataset.


## 4. Scope And Language

Unlike `policy_records`, text realization is language-specific.

Recommended run scope:

- task family: `policy_text_records`
- run scope: `language`

Recommended placement:

```text
output/
  shared/
    runs/
      policy_records--pr-1/
  zh/
    runs/
      policy_text_records--pt-1/
```

The text run should reference the source `policy_records` run in `lineage.json`.


## 5. Decision Simplification For MVP

The canonical policy layer retains the original fine-grained decision.

This task adds one binary machine field:

- `will_help_now: bool`

Important interpretation:

- `will_help_now` is a downstream branch bit for help-gating style composition
- it is not the only semantic control field
- canonical semantic control still comes from `policy_decision` and `policy_strategy`

MVP mapping:

- `true`: none in v1 except direct "help now" style decisions we explicitly allow
- `false`: `engage_briefly`, `defer`, `decline`, `minimal_acknowledgment`, `set_boundary`, `redirect_channel_or_time`

For the current MVP, user preference is:

- `engage_briefly` counts as `false`

Recommended v1 mapping:

- `true`: `engage_now`
- `false`: every other decision value

This gives a very simple operational interpretation:

- `true` means "emit immediate help behavior branch"
- `false` means "do not emit the help tool call branch now"


## 6. Output Schema

Recommended runtime shape now has two layers:

- `artifacts/items/*.json` stores an internal archival record with embedded
  `source_policy`
- `views/export.jsonl` stores the stable downstream contract

Contract notes:

- artifact records are internal archival snapshots and require `source_policy`
- export records are strict projections of artifact records and must not carry
  `source_policy`
- `relation_kind` is a producer-side required field in both layers
- export should keep only downstream composition fields plus minimal trace
  fields, not artifact provenance or generation metadata
- both layers should reject unknown extra fields so downstream composition can
  trust the schema boundary

Suggested artifact shape for each text item:

```json
{
  "schema_version": "1.1",
  "record_id": "policy_text__policy_rec__000123__r01",
  "language": "zh",
  "source_policy_record_id": "policy_rec__000123",
  "relation_kind": "friend",
  "will_help_now": false,
  "policy_decision": "defer",
  "response_intent": "defer",
  "belief": "老王是我认识很多年的朋友。我们关系一直不错，但我现在正赶一个临时任务，时间特别紧。",
  "thinking": "我不是不想帮他，只是眼下腾不开手。先说明我现在没法处理，等晚上空下来再帮他。",
  "text_profile": "warm_brief_v1",
  "source_policy": {
    "...": "embedded structured policy record"
  }
}
```

Notes:

- `source_policy` should stay embedded in the artifact record.
  It is the internal archival snapshot for traceability and validation.
- `policy_decision` is denormalized for easier filtering without traversing
  nested fields.
- `response_intent` keeps surface intent explicit for later composition.
- `will_help_now` is a branch-control bit, not the only control field.
- `belief` and `thinking` are human-readable but must not be the only source of
  truth.
- `source_policy` is a frozen convenience snapshot in artifacts only.
  The canonical source of truth remains the upstream `policy_records` item.
- `relation_kind` must be derived from the embedded source policy relation label
  rather than guessed independently.
- artifact is not the public downstream contract for v1; export below is.

Suggested export shape:

```json
{
  "schema_version": "1.1",
  "record_id": "policy_text__policy_rec__000123__r01",
  "language": "zh",
  "source_policy_record_id": "policy_rec__000123",
  "relation_kind": "friend",
  "will_help_now": false,
  "policy_decision": "defer",
  "response_intent": "defer",
  "belief": "老王是我认识很多年的朋友。我们关系一直不错，但我现在正赶一个临时任务，时间特别紧。",
  "thinking": "我不是不想帮他，只是眼下腾不开手。先说明我现在没法处理，等晚上空下来再帮他。"
}
```

The export is intentionally thinner than the artifact.
It should be rebuilt from artifacts, and rebuild should fail hard if any stored
artifact violates the producer contract.
- keep `source_policy_record_id` as the minimal trace link back to the source
  policy item
- keep internal generation metadata and embedded `source_policy` in artifacts
  only


## 7. Text Semantics

### `belief`

`belief` is input-side context.

It should be:

- first-person
- concise
- natural
- grounded in structured fields

It should usually mention some combination of:

- who the other person is to me
- how close or tense the relationship is
- whether I trust them
- my current energy / time / clarity state
- any local obligation or regret pressure

It should not include:

- explicit field names
- exhaustive structured dumps
- long emotional monologues
- the final decision stated in a formal label-like way

### `thinking`

`thinking` is output-side visible reasoning.

It should be:

- short
- varied in phrasing
- explicit about the practical conclusion
- no long chain-of-thought

Recommended form:

- one to three sentences
- visible reason
- action conclusion

Examples:

- "我现在时间卡得太紧，先不接这个事。等今晚忙完了，我再回他。"
- "这件事我现在能顺手处理，不需要再拖。那我就直接帮他。"
- "我心里其实有点别扭，不想现在接这个请求。先把边界说清楚。"

This field is intentionally visible and short.

It is not hidden chain-of-thought.


## 8. Diversity Strategy

The text task should not collapse into one rigid wording pattern.

Recommended diversity sources:

1. style profile selection
2. prompt instructions that ask for natural paraphrase variation
3. temperature above pure-deterministic decoding
4. optional later support for multiple realizations per source policy

Suggested v1 style profile pool:

- `warm_brief`
- `neutral_direct`
- `guarded_soft`
- `busy_practical`
- `close_relationship_candid`

The style profile is not the semantic truth.

It is a realization hint used to vary wording while preserving the same policy
record.


## 9. Prompting Guidance

This task is LLM-backed.

The model should receive:

- a compact realization-oriented projection of the source policy
- the derived binary label `will_help_now`
- the derived structured `response_intent`
- one chosen `text_profile`
- strict output instructions

Preferred output format:

```json
{
  "belief": "...",
  "thinking": "..."
}
```

Prompt rules:

- keep `belief` first-person
- keep `thinking` short and visible
- preserve the binary action implication
- preserve the finer-grained `response_intent`
- do not invent impossible facts outside the policy slices
- do not explicitly expose raw labels like `role_obligation=high`
- do not produce hidden-thought-style long reasoning
- use `reason_tags` only as hints, not as a checklist to restate

Recommended realization input shape:

```json
{
  "relation": {
    "label": "同事",
    "closeness": "medium",
    "trust": "low",
    "obligation": "high",
    "tension": "low",
    "reciprocity": "neutral",
    "power": "equal"
  },
  "state": {
    "energy": "high",
    "time_pressure": "medium",
    "clarity": "low",
    "emotional_activation": "low",
    "social_readiness": "neutral",
    "confidence": "medium"
  },
  "request_context": {
    "is_doable_now": true
  },
  "decision": {
    "will_help_now": false,
    "response_intent": "defer",
    "policy_decision": "defer",
    "policy_strategy": "defer_with_time_hint"
  },
  "reason_tags": [
    "can_do_later",
    "clarity_constrains",
    "trust_constrains_engagement"
  ]
}
```

Important v1 constraint:

- when `will_help_now == false`, `thinking` must clearly indicate "not helping
  right now"
- it may imply delay, refusal, boundary, brush-off, or redirect
- but it should not drift into "actually helping now"
- false-branch realizations should still distinguish `defer`, `decline`,
  `acknowledge_only`, `set_boundary`, and `redirect`


## 10. Validation Rules

Minimum validation:

- `belief` is non-empty
- `thinking` is non-empty
- both are strings
- `belief` is first-person oriented
- `thinking` is short enough for inspection
- `will_help_now` matches the mapped source decision

Recommended heuristic validation:

- reject very long `thinking`
- reject outputs that contain raw schema jargon such as `relation_closeness`
- reject outputs where `will_help_now == false` but `thinking` clearly says the
  agent will help immediately
- reject outputs where `will_help_now == true` but `thinking` refuses or delays
- reject outputs where `response_intent == defer` but the text sounds like
  outright decline

Failure handling should distinguish:

- source validation failure before any LLM call
- realization parse failure
- realization semantic validation failure
- artifact contract validation failure before item persistence
- export rebuild failure when validating persisted artifacts

Recommended v1 behavior:

- deterministic source validation failures should stop the run immediately
- retry only LLM-backed realization failures a bounded number of times
- if the realization still fails, append to `system/failures.jsonl`
- continue the run for retriable realization failures
- artifact validation and export rebuild failures should stop the run
- `--resume` should validate all existing artifacts and rebuild `views/export.jsonl`
  before any new generation starts
- if all requested items already exist after resume validation, the run should
  exit without initializing the LLM client

Teacher-side validation can start with simple lexical checks plus spot review.


## 11. Run Layout

Recommended run layout:

```text
output/zh/runs/policy_text_records--pt-1/
  run.json
  config.json
  lineage.json
  manifest.json
  work/
    run_state.json
  artifacts/
    items/
      policy_text__policy_rec__000001__r01.json
  views/
    export.jsonl
  system/
    failures.jsonl
```

This matches the existing first-class derived-run conventions.


## 12. Lineage And Config

`lineage.json` should include `sources[]` entries with:

- `task_family`
- `run_id`
- `path`
- `use`
- `artifact_ref`
- optional `filters`

`config.json` should include local execution parameters only, such as:

- model name
- temperature
- max records
- max attempts


## 13. Implementation Strategy

Recommended implementation path:

1. add a new task family `policy_text_records`
2. add Pydantic model(s) for the text item
3. add a text-realization helper that:
   - reads source structured records
   - derives `will_help_now`
   - derives `response_intent`
   - picks a style profile
   - calls the LLM
   - validates the result
4. add a new task main / subcommand for generating the text run
5. persist item JSON files and rebuild `views/export.jsonl`

For v1, one text item per source policy record is enough.

Future versions may support:

- multiple realizations per source record
- richer `belief` verbosity modes
- bilingual generation
- direct downstream projection into `observation / belief / me`


## 14. Recommended MVP

The MVP should:

1. take one `policy_records` run as input
2. generate one Chinese text realization per source item
3. persist both artifact and export views from the same validated record
4. require `relation_kind` in both artifact and export
5. add `will_help_now: bool`
6. treat only `engage_now` as `true`
7. keep `thinking` short and visible
8. keep `response_intent` explicit
9. avoid combining with QA in this step

This is the smallest version that still unlocks the downstream composition work.


## 15. Success Criteria

This task is successful if:

- every source policy record can be turned into a valid text item
- `will_help_now` is easy to filter and rebalance on
- text remains semantically aligned with the structured source policy
- realizations are varied enough to avoid one-template collapse
- downstream QA composition can consume this dataset without needing to
  reinterpret raw policy slices from scratch
