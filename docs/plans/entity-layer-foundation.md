# Entity Layer Foundation Plan

This document defines a reusable entity layer for agentic-context data
generation.

It is not only a help-gate enhancement.

It is intended to become shared infrastructure for multiple downstream tasks,
including:

- help / not-help composition
- conflict-scene synthesis
- collaboration-scene synthesis
- memory, summary, and retrieval projections
- future ACML action-bearing samples


## 1. Goal

Introduce a lightweight but reusable entity layer that lets generated samples
represent:

- who the agent is interacting with
- how that other entity is named in text
- how that entity relates to the agent
- how the same entity can be referred to consistently across observation,
  belief, thinking, and future actions

The main benefit is to shift training data away from chat-style `I/you`
framing and toward world-model-style `I and other entities in a shared world`
framing.


## 2. Why This Matters

Chat-first assistants can get away with heavy use of second-person language
because the runtime interaction model is:

- one assistant
- one user
- one immediate conversation partner

Our target agentic setting is different.

The intended model should learn something closer to:

- I persist through time
- many different people can address me
- those people are not all "you"
- I may think about them, remember them, search over them, and act toward them
- external interaction is not the same thing as inner monologue

If training text keeps collapsing other entities into generic `你`-style
addressing, the learned representation tends to stay chat-shaped even when the
surface format is agentic.


## 3. Problem Statement

The current samples already support useful first experiments, but they still
show three limitations:

### 3.1 Other entities are weakly anchored

Current samples often use:

- `这位同事`
- `对方`
- implicit `你`

These are locally readable, but they do not create a strong reusable entity
anchor for:

- summaries
- retrieval
- cross-sample consistency
- later action references

### 3.2 Text realization still carries chat habits

Even when `me` is intended to be internal reasoning, generated `thinking`
language can drift toward:

- `我来帮你`
- `我先回你`
- `我现在帮你处理`

This sounds like a direct outward reply, not an internal agent-side reasoning
stream about another entity in the world.

### 3.3 The current pipeline has relation modeling but not entity modeling

The existing policy/help-gate pipeline already captures:

- relation kind
- closeness
- trust
- obligation
- tension
- reciprocity

But it does not yet represent:

- a stable entity id
- a stable human-readable name
- first-mention vs later-mention naming conventions
- a shared machine/text bridge for later action references


## 4. Design Principles

The entity layer should follow these principles.

### 4.1 Reusable beyond one task

It must not be baked into help-gate only.

It should be usable by future tasks that need:

- one counterparty
- multiple people in one scene
- repeated references to the same entity
- structured action targets

### 4.2 Lightweight first, extensible later

The first implementation should support a single primary counterparty cleanly.

It should not require a full simulation engine, global memory graph, or
realistic person biography system.

But its shape should not block later extension to multi-entity scenes.

### 4.3 Explicit machine anchor plus readable text anchor

Each entity should have both:

- a stable machine id
- a readable textual name

Either one alone is insufficient.

### 4.4 No gender guessing, no unnecessary persona invention

The first version should avoid:

- inferred gender
- invented backstory
- rich demographic profiling
- unstable style-heavy naming

The point is stable anchoring, not fictional richness.

### 4.5 Internal thought should not masquerade as direct address

In ACML:

- `me` is inner monologue / reasoning stream
- outward interaction belongs to future `<acml:action>`

So entity references in `me` should usually be third-person or name-based,
not second-person address.


## 5. Core Proposal

Introduce a small shared entity representation with two layers:

- an upstream language-neutral identity anchor
- a downstream controlled mention projection used by generated text

This distinction is important in the current repo because:

- `policy_records` is treated as semantic truth
- `policy_text_records` is language-specific realization
- help-gate currently consumes only the thin `policy_text` export contract

Recommended upstream semantic concept:

```json
{
  "entity_id": "person__policy_rec__000123__primary",
  "entity_type": "person",
  "name_key": "name_slot_0042"
}
```

Recommended downstream controlled mention projection concept:

```json
{
  "canonical_name": "周宁",
  "first_mention_name": "周宁[coworker]"
}
```

Interpretation:

- `entity_id`: stable machine key
- `entity_type`: future-proof slot for person / group / organization
- `name_key`: deterministic language-neutral naming anchor
- `canonical_name`: readable anchor for later mentions
- `first_mention_name`: controlled first-mention projection using a stable
  template rather than natural-language-specific phrasing

Important scope rule:

- upstream `counterparty.entity_id` is a record-local anchor
- it is not globally unique across runs
- it does not claim persistent cross-run identity continuity

This is intentional because the project is primarily synthetic training-data
generation. The goal is sample diversity and flexible recomposition, not a
single persistent simulated world.


## 6. Scope Of V1

The first implementation should support exactly one primary non-self entity per
record.

That entity is:

- the person who is addressing the agent
- the person whose request the policy layer is evaluating
- the person who will later become the target of possible actions

V1 does not need to model:

- multiple simultaneous people in one sample
- family trees
- social groups
- name disambiguation across an entire corpus
- persistent cross-run identity continuity

V1 explicitly treats upstream counterparty identity as local to a single
policy record. If multiple runs contain `policy_rec__000123`, their
counterparty ids may repeat without implying that they refer to the same
person.

Those can come later.


## 7. Canonical Semantic Shape

### 7.1 Suggested upstream shared slice

Recommended reusable slice name:

- `counterparty`

Suggested v1 upstream shape:

```json
{
  "counterparty": {
    "entity_id": "person__policy_rec__000123__primary",
    "entity_type": "person",
    "name_key": "name_slot_0042"
  }
}
```

This should sit alongside the existing relation/state/policy slices, not
replace them.

Important separation:

- relation slice = semantic relationship state
- entity slice = which non-self entity is being referenced
- mention projection = downstream readable/control-form projection derived
  from `name_key` plus relation semantics

### 7.2 Suggested downstream projected fields

The first implementation will still need a minimal controlled entity mention
projection for downstream tasks.

Suggested projected shape:

```json
{
  "counterparty_mention": {
    "entity_id": "person__policy_rec__000123__primary",
    "canonical_name": "周宁",
    "first_mention_name": "周宁[coworker]"
  }
}
```

This projected shape should live in downstream layers such as
`policy_text_records`, not in `policy_records`.

It is a projection shape, not the new universal semantic source of truth.


## 8. Naming Strategy

The naming strategy matters a lot.

### 8.1 Recommended v1 policy

Use:

- a stable neutral name or short display name
- plus a controlled relation-bearing first mention form

Recommended v1 pattern:

- first mention: `<canonical_name>[<relation_kind>]`
- later mentions: `周宁`

Example:

- first mention: `周宁[coworker]`
- later mentions: `周宁`

V1 should intentionally avoid natural-language-specific relation phrases such
as `同事周宁` or `a coworker named Zhou Ning` as the canonical projection.
Those can be added later as optional style projections, but the foundation
layer should use one stable template across Chinese and English generation.

Current recommendation:

- `first_mention_name = f"{canonical_name}[{relation_kind}]"`

because it is:

- compact
- readable
- easy to validate
- independent of surface language
- explicit about relation at first mention
- suitable for inner-monologue text where consistency matters more than
  conversational naturalness

### 8.2 Recommended constraints

- do not infer gender
- use a curated pool of neutral or low-gender-salience names
- do not generate names with LLM free-form creativity
- keep names deterministic from record identity / `name_key` where possible

### 8.3 Determinism

Name assignment needs two levels of determinism.

Upstream identity determinism:

- `entity_id` and `name_key` should be anchored to `policy_records.record_id`
  or equivalent semantic identity input
- they should not depend on downstream language-specific text-run seeds

Downstream mention determinism:

- `name_key` should deterministically resolve to the same `canonical_name`
- `relation_kind + canonical_name` should deterministically resolve to the
  same `first_mention_name`

This improves:

- reproducibility
- debugging
- regeneration stability
- cross-run comparability


## 9. Text Projection Rules

### 9.1 Observation

Current style:

```text
这位同事对我说：<payload>...</payload>
```

Recommended v1 entity-aware style:

```text
周宁[coworker]对我说：<payload>...</payload>
```

This keeps relation salience while adding an entity anchor. It is deliberately
a controlled projection rather than idiomatic prose.

### 9.2 Belief

Belief should use the entity name naturally:

```text
周宁[coworker]平时和我合作还算顺，但我今天精力不太够。
```

Not preferred:

- `这位同事平时和我合作还算顺`
- `你平时和我合作还算顺`

### 9.3 Thinking / me

`me` should remain internal monologue, so preferred patterns are:

```text
周宁[coworker]这件事我现在不想直接接。
先把手头事情做完，再决定要不要帮周宁处理。
```

Avoid chat-like direct address:

- `我现在先不帮你`
- `我晚点回你`
- `我来帮你`

Those can be valid future outward messages, but they belong in action-bearing
projections later, not in internal monologue by default.


## 10. ACML Implications

The entity layer should improve ACML samples in two ways.

### 10.1 Immediate textual improvement

Even before introducing actions, it improves:

- entity clarity in `observation`
- entity tracking in `belief`
- non-chat framing in `me`

### 10.2 Future structured references

The layer should also prepare for future `<acml:action>` use.

Recommended future-compatible direction:

- retain text names in entry content
- optionally attach machine-readable entity attrs when useful

Possible future example:

```text
<acml:entry kind="observation" source="qa" relation="coworker" entity_id="person__sample__acml_abc__primary" source_entity_id="person__policy_rec__000123__primary" entity_name="周宁">
周宁[coworker]对我说：<acml:payload>...</acml:payload>
</acml:entry>
```

And later:

```text
<acml:action target_entity_id="person__sample__acml_abc__primary">...</acml:action>
```

For help-gate ACML, action-targetable entity ids should be sample-local. The
QA payload and the policy-text counterparty name are intentionally recombined
for synthetic diversity, so the ACML-facing target id should identify the
counterparty inside that sample, not claim persistent identity across all
payloads paired with the same policy-text record.

V1 does not need to commit to final action attrs yet, but the entity layer
should make this source-vs-sample identity split straightforward.


## 11. Proposed Pipeline Integration

### 11.1 Shared entity infrastructure

Add a small reusable entity module, for example:

- `entity_catalog.py`
- or `social_entities.py`

This module should own:

- entity slice dataclasses / models
- deterministic name assignment helpers
- curated name pools
- controlled first-mention helpers such as
  `first_mention_name_for(relation_kind, canonical_name)`
- sample-local entity id helpers for downstream composed samples

Important ownership rule:

- `relation_catalog.py` should remain relation-only
- the new entity module should own `relation_kind + name -> mention` helpers
- help-gate should call that shared helper rather than assembling names inline

### 11.2 Policy records

Extend `policy_records` generation to include `counterparty`.

This is the best long-term home because the entity anchor is part of the world
state, not just a help-gate projection trick.

### 11.3 Policy text records

Text realization should consume:

- the upstream `counterparty` identity slice
- controlled mention projection derived from `name_key` and `relation_kind`

The prompt/input contract should be extended explicitly before prompting.

Recommended realization-input addition:

```json
{
  "counterparty_mention": {
    "entity_id": "person__policy_rec__000123__primary",
    "canonical_name": "周宁",
    "first_mention_name": "周宁[coworker]"
  }
}
```

Prompts should explicitly require:

- use of the entity name
- avoidance of second-person address for the counterparty
- preservation of inner-monologue framing
- removal of the old generic fallback rule that permits `对方/这位同事`
  when identity is available

Validation should check:

- belief contains a name anchor
- thinking contains a name anchor when natural
- forbidden second-person patterns are minimized or banned

### 11.4 Help-gate ACML

Help-gate composition should:

- use the controlled first-mention projection in observation
- rely on policy-text outputs for belief and thinking text
- use sample-local entity ids for ACML-facing target identity if entity attrs
  are added
- optionally carry through the upstream policy-text entity id separately as a
  source/provenance id

Concretely, help-gate should keep calling a shared projection helper rather
than hardcoding concatenation logic inside `help_gate_acml.py`.


## 12. Why The Entity Layer Belongs Upstream Of Help-Gate

It would be tempting to patch only help-gate composition by replacing:

- `这位同事`

with:

- `周宁[coworker]`

That would improve observation text, but it would not solve the deeper issue.

The real problem also affects:

- belief realization
- thinking realization
- validation
- future action targeting
- downstream summary/search over people

So the right ownership is upstream shared infrastructure, not a task-local text
patch.


## 13. Contract Boundaries And Source Of Truth

The first implementation should state these boundaries very explicitly.

### 13.1 Single source of truth for relation semantics

Relation semantics should remain owned by the existing relation machinery:

- relation slice fields in `policy_records`
- canonical relation mapping / projection helpers

The entity layer should not become a second source of truth for relation kind.

That means:

- `counterparty` should not own semantic `relation_kind`
- first-mention forms like `周宁[coworker]` should be derived from relation
  semantics plus name projection

Implementation ownership should stay explicit:

- `relation_catalog.py` owns relation semantics and relation-only wrappers
- the entity module owns `relation_kind + canonical_name -> first_mention_name`
- downstream tasks reuse those helpers rather than forking naming rules

### 13.2 Single source of truth for entity identity

Entity identity should be owned by:

- `counterparty.entity_id`
- `counterparty.name_key`

Rendered names are projections from that identity anchor, not the identity
itself.

For V1, this source-of-truth rule is record-local:

- `counterparty.entity_id` identifies the primary counterparty within a policy
  record
- it is stable under regeneration of that record
- it is not expected to be unique across independent runs
- downstream composed samples may derive their own sample-local entity ids
  from this source id plus the composed sample id

### 13.3 Runtime boundary for help-gate

The current help-gate runtime consumes only the thin `policy_text` export.

So if help-gate is expected to use entity-aware observation names without
reopening artifacts, then the `policy_text` export contract must be extended
with the minimal projected entity fields it needs.

Recommended minimal export addition:

```json
{
  "counterparty_entity_id": "person__policy_rec__000123__primary",
  "counterparty_canonical_name": "周宁",
  "counterparty_first_mention_name": "周宁[coworker]"
}
```

The observation first-mention text can then be reused directly or rederived in
help-gate from:

- `relation_kind`
- `counterparty_canonical_name`
- controlled mention projection helpers

If help-gate emits ACML entity attrs, it should derive an ACML sample-local id
from `sample_id` plus `counterparty_entity_id`, and may keep the upstream id in
a separate provenance attr such as `source_entity_id`.


## 14. Validation Recommendations

The first implementation should add explicit validators, not rely on prompt
compliance alone.

Recommended checks:

- each record has a non-empty `entity_id`
- each record has a non-empty `name_key`
- each projected record has a non-empty `canonical_name`
- each projected record has a non-empty `first_mention_name`
- names do not conflict with reserved tokens
- `first_mention_name` follows the controlled `<canonical_name>[<relation_kind>]`
  template
- policy-text outputs avoid raw second-person `你/您` when referring to the
  counterparty
- policy-text outputs contain at least one stable entity reference
- help-gate ACML entity attrs, if emitted, use sample-local target ids rather
  than upstream record-local ids as action targets

Recommended soft checks:

- first mention should prefer the derived controlled first-mention form
- later mention can prefer `canonical_name`
- repeated use of only `对方` should be treated as low quality
- prompt templates, cue inventories, and validators should be migrated
  together, not independently


## 15. Migration And Versioning

This repo uses strict contracts, so the doc should be explicit about migration.

Recommended v1 migration stance:

- no dual-read compatibility
- old runs may be considered invalid for the new pipeline
- regenerate downstream runs after schema changes

Recommended version bumps:

- bump `policy_records` schema version when adding `counterparty`
- bump `policy_text` schema version when extending artifact/export contracts
- bump `help_gate` composition version if observation/entity projection changes
  materially
- include the help-gate composition version in the run config, not only in the
  summary, so resume cannot mix old and new projection rules

Recommended implementation rule:

- land schema changes in one coordinated migration across
  `policy_records -> policy_text_records -> help_gate_acml`
- avoid intermediate states where one layer writes new entity fields but the
  next layer still forbids them


## 16. Multi-Entity Future

Although v1 supports one counterparty, the data model should not trap us there.

The future generalization path should be:

```json
{
  "entities": [
    {"entity_id": "person__policy_rec__000123__primary", "...": "..."},
    {"entity_id": "person__policy_rec__000123__observer", "...": "..."}
  ],
  "scene_roles": {
    "primary_counterparty": "person__policy_rec__000123__primary",
    "observer": "person__policy_rec__000123__observer"
  }
}
```

This would support:

- conflict triangles
- cooperation among multiple people
- referrals and redirections
- memory compression over several recurring entities

V1 does not need this full shape, but it should avoid naming or APIs that make
such growth awkward.

The future multi-entity model should also preserve the distinction introduced
in V1:

- source entity ids can remain local to their source semantic records
- composed samples can mint sample-local ids for entities that become ACML
  action targets
- provenance links can connect sample-local ids back to source ids when useful


## 17. Risks And Tradeoffs

### 17.1 Risk: too much fictionalization

If names are generated too creatively, the corpus may become noisy and harder
to control.

Mitigation:

- deterministic curated pools
- no biographies
- no inferred demographics

### 17.2 Risk: text becomes stilted

The controlled first-mention template is intentionally less idiomatic than
natural language. If every sentence mechanically repeats the full
relation-bearing name, the text will feel stiff.

Mitigation:

- use the derived first-mention form for first mention
- allow `canonical_name` afterwards
- do not require maximal repetition
- treat the template as an inner-monologue/control-form convention rather than
  a conversational style target

### 17.3 Risk: false sense of persistent world continuity

If names repeat across unrelated records, users might over-interpret them as
the same persistent person.

Mitigation:

- document that V1 upstream ids are record-local anchors unless explicitly
  upgraded later
- derive sample-local ACML target ids in composed help-gate samples
- avoid claiming that repeated names or repeated upstream ids imply a persistent
  cross-run person


## 18. Recommended V1 Implementation Order

### Phase 1

Add the shared entity-layer module and the canonical identity slice definition:

- `CounterpartyIdentity`
- `CounterpartyMention`
- record-local identity helpers
- deterministic name helpers
- controlled first-mention helper
- sample-local ACML entity id helper

### Phase 2

Extend `policy_records` with deterministic `counterparty` identity generation:

- `entity_id`
- `entity_type`
- `name_key`

### Phase 3

Update `policy_text_records` prompts and validators to:

- resolve `name_key` into canonical names
- add resolved name fields to `PolicyTextRealizationInput` before prompting
- use entity names
- reduce or ban second-person address for counterparties
- keep `thinking` as inner monologue

Also extend the `policy_text` artifact/export contract with the minimal entity
projection fields downstream tasks need.

### Phase 4

Update `help_gate_acml` projection so observation uses:

- relation semantics from the relation layer
- `counterparty_canonical_name` from `policy_text` export
- the controlled first-mention projection helper
- a sample-local ACML entity id if entity attrs are emitted

### Phase 5

Audit sample outputs and refine naming pools, prompt wording, and validators.


## 19. Concrete First Success Criteria

The first implementation should be considered successful if:

- generated samples stop relying on generic `对方` for the primary entity
- `belief` and `me` usually refer to the counterparty by stable name
- `me` stops reading like a direct reply to `你`
- help-gate ACML action-targetable entity ids are sample-local when present
- help-gate ACML samples remain valid and round-trip cleanly
- the same entity representation can obviously be reused by at least one
  non-help-gate downstream task


## 20. Example Before And After

### Before

```text
observation: 这位同事对我说：<payload>...</payload>
belief: 我现在有点累，而且和对方只是普通同事。
me: 我现在不适合马上帮你，先晚点再处理。
```

### After

```text
observation: 周宁[coworker]对我说：<payload>...</payload>
belief: 周宁[coworker]平时和我只是普通同事关系，我现在也有点累。
me: 周宁[coworker]这件事我现在不想马上接。先把手头事情做完，再决定怎么处理。
```

The second version is more compatible with:

- agent persistence
- multi-entity scenes
- memory and retrieval
- future action supervision


## 21. Recommendation

Proceed with the entity layer as shared upstream infrastructure rather than a
help-gate-only wording patch.

In particular:

- keep shared contract literals in `policy_text_contracts.py` and put entity
  helpers in their own reusable module
- add a reusable entity module
- keep upstream `policy_records` limited to record-local entity identity
  anchors
- push controlled entity mention projection into downstream layers and
  validation
- explicitly extend the `policy_text` export with the minimal entity fields
  help-gate needs
- make help-gate ACML target ids sample-local when entity attrs are emitted
- let ACML projection inherit the improved entity grounding

This is the cleanest path to making the first real training experiments feel
less like chat imitation and more like an agent learning to live among other
entities in the world.
