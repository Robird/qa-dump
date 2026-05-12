# HelpGate ACML Task Plan

This document defines the first end-to-end ACML-producing composition task for
the `help_gate_acml` family.

It sits downstream of:

- QA payload exports
- `policy_records`
- `policy_text_records`

Its purpose is to produce agentic training samples directly in ACML rather than
first emitting a JSON sample dataset and later converting that dataset to ACML.


## 1. Goal

Create a language-scoped run that combines:

- a QA payload
- a policy-text realization

into a single-sample `.acml` document with the semantic shape:

- `observation`
- `belief`
- `me`

The target training lesson is not "assistant replies to user".

It is:

- an agent lives in a world
- different kinds of people address the agent
- the agent has local relationship/state context
- the agent may or may not decide to engage now
- the resulting internal reasoning differs accordingly


## 2. Why Direct ACML

Direct ACML is the preferred first output mode because:

- ACML is already the desired downstream authoring format
- the target sample structure is naturally `observation / belief / me`
- a JSON-first export would introduce an extra format layer without adding much
  value for the MVP
- the ACML library already provides parser and serializer support

Important implementation nuance:

- we should still build a typed semantic object in memory first
- we should not hand-concatenate ACML strings as the main construction path

Recommended flow:

```text
QA payload + policy_text record
  -> task-local semantic composition object
  -> ACML Document model
  -> ACML serializer
  -> .acml file
  -> ACML parser round-trip validation
```

This is still "direct ACML output" because the semantic object is only an
in-memory construction aid, not a separate persisted dataset format.

Implementation note for the first clean release:

- keep a single ACML round-trip boundary:
  `SemanticDocument -> serialize -> parse-back -> typed validation`
- avoid parsing the serialized text twice
- keep validation on the parse-back `Document`, not only on the authoring-side
  semantic object


## 3. Task Boundary

### Inputs

- QA run: `qa_corpus` view `qa_export_sft_v1`
- policy-text run: `policy_text_records` export

### Output

- one `.acml` file per composed sample

### Non-goals for v1

- tool-call training
- multi-turn ACML threads
- name/persona synthesis
- indirect relation reasoning from names or pronouns
- separate loss-policy markup

Clarification:

- v1 may still use `<acml:action>` as mixed content inside the `me` entry for
  outward reply-bearing branches
- the non-goal is a separate top-level `action` entry or a task-specific
  action DSL beyond basic reply projection

Important input-contract rule:

- `policy_text_records` export must expose the minimum relation-wrapper field
  needed for ACML observation projection
- v1 should add a canonical relation enum such as `relation_kind` to the
  policy-text export, rather than forcing this task to re-open artifact-only
  snapshots


## 4. Placement And Run Shape

Preflight and generation should share one task-local source plan that owns:

- QA payload discovery and filtering
- policy-text export loading
- deterministic pairing strategy
- estimated sample count and preview statistics

This keeps the preflight report aligned with the actual generation semantics.

Implementation note:

- the canonical runtime boundary should be a single executable source plan
  object, not a `resolved sources` wrapper plus a second `plan` object
- if a compatibility module such as `help_gate_sources.py` remains, it should
  delegate to the source-plan implementation rather than owning parallel task
  semantics

Recommended run placement:

```text
output/
  zh/
    runs/
      help_gate_acml--hg-acml-1/
```

Recommended run layout:

```text
help_gate_acml--hg-acml-1/
  run.json
  config.json
  lineage.json
  manifest.json
  work/
  artifacts/
    items/
      acml__<lineage-hash-1>.json
      acml__<lineage-hash-2>.json
    samples/
      acml__<lineage-hash-1>.acml
      acml__<lineage-hash-2>.acml
  views/
  system/
```

Important choices:

- `artifacts/items/*.json` is the lightweight completion ledger
- `artifacts/samples/*.acml` is the primary textual sample artifact
- no JSONL sample export in the MVP
- `views/` may remain empty in v1
- upstream provenance stays in run metadata, not stuffed into ACML body text


## 5. Sample Structure

Each sample should be a standalone ACML document:

```text
<acml version="0" task="help_gate_acml_v1" language="zh" sample_id="...">
<acml:entry kind="observation" source="qa" relation="coworker">
这位同事对我说：<acml:payload>问题原文...</acml:payload>
</acml:entry>

<acml:entry kind="belief" source="policy_text">
我现在时间有点紧，脑子也不太清楚，而且和对方只是普通同事。
</acml:entry>

<acml:entry kind="me" source="policy_text+qa" will_help_now="false" response_intent="defer">
我现在不适合马上接这个事，先晚点再处理。
</acml:entry>
</acml>
```

Recommended interpretation:

- `observation`: what the world says to me
- `belief`: my already-known local context
- `me`: my current internal reasoning stream

Important semantic constraint:

- `me` is not a final outward reply channel
- in the native agentic framing, visible output and external messaging would be
  tool calls, which are out of scope for this MVP


## 6. Observation Projection

`observation` must not present every request as coming from a generic "user".

Instead it should wrap the QA question in a relation-aware but neutral framing.

Recommended shape:

- wrapper text outside payload
- raw question inside `<acml:payload>`

Example:

```text
这位同事对我说：<acml:payload>哥特式建筑起源于哪个时期？</acml:payload>
```

This preserves two useful distinctions:

- the social source of the request
- the literal opaque request text itself

### v1 relation wrapper projection

Recommended neutral mapping:

- `coworker` <- `同事` -> `这位同事对我说：`
- `partner` <- `合作伙伴` -> `这位合作伙伴问我：`
- `friend` <- `朋友` -> `这位朋友对我说：`
- `stranger` <- `陌生人` -> `一个陌生人问我：`
- `other` <- fallback -> `对方对我说：`

Rules:

- the `relation` attribute stores the canonical enum on the left side above
- wrapper text is a language-specific projection from that canonical enum
- the implementation should cover the current policy-layer relation inventory,
  not only the four examples above; new upstream relation labels should require
  an explicit canonical mapping instead of silently collapsing into `other`
- do not invent personal names
- do not infer gender
- do not add new scene details
- preserve the source QA question text semantically inside `payload`
- after ACML parse-back, the payload text must exactly equal the original QA
  question text
- relation wrapper text should come from a language-scoped table keyed by the
  canonical `relation_kind`, not from ad hoc branching scattered across the
  pipeline


## 7. Belief Projection

`belief` should directly reuse the textual belief already generated in
`policy_text_records`.

Recommended v1 behavior:

- use `policy_text_record.belief` as the natural-language core
- prepend a compact runtime affordance prelude when the task wants to expose
  available outward actions explicitly
- do not add QA answer text here
- do not restate the entire structured policy snapshot

Reason:

- `policy_text_records` already exists to express relation/state context in a
  compact natural form
- a short runtime affordance declaration can live alongside belief without
  forcing the LLM to infer an action API from thin air
- re-realizing the belief prose itself during composition would create
  unnecessary instability

Recommended minimal runtime affordance style:

```text
我当前可调用的外部动作原型：
void SendMessage(string target_entity_id, string message);
```

Recommended v1 variation rule:

- sample one reply-tool name from a small curated inventory per sample
- sample one runtime affordance prelude from a small curated inventory per
  sample
- keep that choice deterministic from `sample_id` for reproducibility
- derive the reply-tool name and the prelude variant independently so local
  diversity grows without breaking sample-internal consistency
- the same sampled name must appear consistently in both the belief prototype
  and the `me` action call
- keep the prototype signature itself stable across variants; only vary the
  surrounding natural-language lead-in lightly


## 8. Me Projection

`me` is the most important training-bearing entry in this task.

### v1 interpretation

`me` is internal reasoning text, not an external assistant message.

Implementation note:

- `me` surface composition should be table-driven by `response_intent`
- non-help branches may remain text-only in v1
- `help_now` should attach the outward reply as `<acml:action>` mixed content
  rather than inlining the QA answer into internal monologue text

### When `will_help_now == true`

`me` should contain:

- `policy_text_records.thinking`
- one reply-bearing `<acml:action>` whose content is a minimal tool-style
  invocation and whose payload preserves the QA source answer content

This keeps internal reasoning and outward interaction separated while still
preserving the QA answer as the knowledge authority.

Important rule:

- preserve QA answer truth as the knowledge authority
- keep the answer content inside the action payload rather than rewriting it
  into the `thinking` text
- use one fake-but-explicit reply tool name sampled from a small inventory
  such as `SendMessage`, `SendMsg`, `send_message`, `Speek`, or `speek`
- do not fabricate a substantively different answer

Recommended v1 action style:

```text
<acml:action tool="SendMessage" dialect="csharp-v0" target_entity_id="person__sample__...">
SendMessage(target_entity_id: "person__sample__...", message: <acml:payload>...</acml:payload>)
</acml:action>
```

### When `will_help_now == false`

`me` should contain:

- `policy_text_records.thinking`
- optional short extension text if needed for fluency

It must not contain:

- the QA answer content
- a leaked near-answer
- a hidden full explanation disguised as hesitation

This keeps the non-help branch aligned with the downstream "no immediate help
tool/action" interpretation.


## 9. Composition Record In Memory

Although the task writes only `.acml`, it should still form a small internal
composition object before serialization.

Suggested task-local fields:

```json
{
  "sample_id": "...",
  "language": "zh",
  "payload": {
    "payload_id": "...",
    "request_text": "...",
    "fulfillment_content": "...",
    "domain_slug": "...",
    "bloom_level": "..."
  },
  "policy_text": {
    "record_id": "...",
    "source_policy_record_id": "...",
    "relation_kind": "coworker",
    "will_help_now": false,
    "response_intent": "defer",
    "policy_decision": "defer",
    "belief": "...",
    "thinking": "..."
  },
  "projection": {
    "observation_wrapper": "这位同事对我说：",
    "me_text": "..."
  }
}
```

This object is only for deterministic construction and validation.

It should not be exported as a separate dataset format in v1.


## 10. ACML Construction Strategy

The task should use `/repos/acml` as the authoring backend.

Recommended construction path:

1. build task-local composition object
2. project into ACML `SemanticDocument`
3. convert with `semantic_document_to_document()`
4. serialize with `acml.serialize_document`
5. parse back with `acml.parse_document`
6. fail the sample if round-trip parse fails

Recommended root attributes:

- `version="0"`
- `task="help_gate_acml_v1"`
- `language="<lang>"`
- `sample_id="<id>"`

Recommended entry attributes:

- `observation`
  - `source="qa"`
  - `relation="<canonical relation enum>"`
- `belief`
  - `source="policy_text"`
- `me`
  - `source="policy_text+qa"`
  - `will_help_now="true|false"`
  - `response_intent="..."`
  - `policy_decision="..."`

Not included in v1:

- `loss`
- document-level lineage references inside ACML

Included in v1:

- optional `<acml:action>` mixed content inside the `me` entry for
  reply-bearing branches
- lightweight action attrs such as `tool`, `dialect`, and `target_entity_id`
  when the projection task wants to teach a concrete reply primitive

Important future-compatibility rule:

- if later versions add tool/action supervision, they must still preserve the
  same three top-level entries
- `action` can only appear as mixed content inside the `me` entry
- do not introduce a fourth top-level `action` entry


## 11. Pairing And Sampling

The task should combine:

- discovered QA payloads
- discovered policy-text records

The first version may use a simple deterministic pairing strategy, but it
should still be explicit and reproducible.

Recommended MVP strategy:

- anchor on QA payloads
- enumerate QA payloads in stable order after filters
- enumerate policy-text export records in stable order
- set `pair_count` to the number of retained QA payloads unless
  `--max-samples` asks for fewer
- pair each QA payload with one policy-text record by deterministic modular
  indexing over the policy-text list
- allow policy-text reuse by cycling only on the policy-text side

This makes the anchor side explicit and avoids silently reusing the first few
QA payloads when the two pools are imbalanced.

Possible future improvements:

- target ratio control for `will_help_now`
- domain-balanced QA sampling
- response-intent stratification
- multiple ACML realizations per same pair

The MVP should optimize for simplicity and reproducibility first.


## 12. Validation Rules

Minimum validation should check:

- source QA payload is valid
- source policy-text record is valid
- ACML serialization succeeds
- ACML parse-back succeeds
- document has exactly three entries in order:
  - `observation`
  - `belief`
  - `me`
- `observation` contains exactly one payload node with the original question text
- `belief` is non-empty
- `me` is non-empty
- `will_help_now == false` implies `me` contains no reply action carrying the
  source QA answer

Recommended extra validation:

- `belief` begins with the configured runtime affordance prelude when reply
  tools are enabled for the task
- the sampled runtime affordance prelude variant is deterministic from
  `sample_id`
- the sampled reply-tool name matches between belief prototype and `me` action
- `will_help_now == true` implies `me` contains exactly one reply action whose
  payload equals the source QA answer
- `will_help_now == true` implies `thinking` text itself does not inline the
  source QA answer
- non-help branches do not leak long answer-like spans
- ACML attributes do not contain forbidden characters


## 13. Output Identity

Suggested sample id shape:

```text
acml__<stable_hash_of_lineage_tuple>
```

Recommended lineage tuple:

```text
(
  qa_run_id,
  qa_view_id,
  qa_record_id,
  policy_text_run_id,
  policy_text_record_id,
  language
)
```

Suggested artifact filename shape:

```text
acml__<stable_hash_of_lineage_tuple>.acml
```

The canonical lineage key should still be recoverable from run metadata and
from the root `sample_id` attribute.


## 14. CLI Shape

Recommended command family:

```bash
python help_gate_main.py \
  --run-id hg-acml-1 \
  --language zh \
  --qa-run-id <qa-run> \
  --policy-text-run-id <pt-run>
```

Recommended flags:

- `--run-id`
- `--language`
- `--qa-run-id`
- `--qa-run-dir`
- `--policy-text-run-id`
- `--policy-text-run-dir`
- `--max-samples`
- `--domains`
- `--bloom-levels`
- `--resume`
- `--preflight-only`
- `--verbose`


## 15. Manifest Summary

Run summary should include at least:

- source QA run id
- source QA view id
- source QA export schema/version
- source policy-text run id
- source policy-text export schema/version
- generated sample count
- skipped existing count
- `will_help_now` distribution
- `response_intent` distribution
- QA domain distribution
- pairing strategy
- sample-id policy
- active filters such as domains, bloom levels, and max-samples
- output path


## 16. Why No JSON Export In MVP

Skipping a separate JSON sample export is a deliberate simplification.

Benefits:

- one canonical artifact format
- less schema design overhead
- fewer projection layers to keep in sync
- faster end-to-end validation against the actual downstream format

Tradeoff:

- some ad hoc inspection tasks become slightly less convenient

This is acceptable because:

- run metadata still provides lineage
- ACML samples are parseable back into structured nodes
- a JSON projection can still be added later if experiments demand it


## 17. Success Criteria

This task is successful if:

- we can generate a stable ACML run from QA + policy-text inputs
- the ACML parses cleanly with the shared ACML library
- `observation` reflects relation-aware world input rather than generic
  "user says"
- `belief` carries the local social-state context
- `me` includes answer content only in the immediate-help branch
- non-help branches do not leak the QA answer
- the resulting samples look like "agent in world" context rather than
  assistant chat logs


## 18. Future Extensions

Likely next extensions after the MVP:

- LLM rewriting of `me` for more natural integrated reasoning
- explicit `action` generation inside the `me` entry once tool-call
  supervision is ready
- richer relation wrapper projection with names/pronouns/indirect relations
- multi-turn ACML threads
- optional JSON or semantic export views
- stronger answer-leak detection for non-help branches
