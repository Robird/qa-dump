# Output Layout Refactor Plan

This document rethinks the on-disk output layout for QA-Dump and the new policy/help-gate workstreams.

The core problem is not just naming.

It is that the current layout mixes several different concepts into one directory tree:

- long-lived task runs
- task-internal raw artifacts
- aggregate exports
- downstream derived or orthogonal datasets

This creates two structural errors:

1. orthogonal tasks are nested as if they depended on one parent run
2. unrelated artifact categories are mixed as siblings inside one run directory


## 1. Current Problems

The current shape under [output/zh/runs/ds-2](/repos/qa-dump/output/zh/runs/ds-2) mixes:

- raw QA generation artifacts for each domain
- run-level export summaries under `exports/`
- orthogonal policy/help-gate outputs under `derived/`
- run metadata such as `run.json`

This is semantically confused.

Examples:

- [output/zh/runs/ds-2/derived/policy_records](/repos/qa-dump/output/zh/runs/ds-2/derived/policy_records) is not truly a child of the `ds-2` QA run
- [output/zh/runs/ds-2/exports](/repos/qa-dump/output/zh/runs/ds-2/exports) is an export view, not the same kind of thing as [output/zh/runs/ds-2/agricultural_sciences](/repos/qa-dump/output/zh/runs/ds-2/agricultural_sciences)

The deeper issue is conceptual:

- a QA corpus run is one long-cycle task
- policy record generation is another long-cycle task
- help-gate composition is a third long-cycle task

These should be parallel first-class runs, not nested under one another.


## 2. Design Goals

The refactor should satisfy these goals:

1. `output/<lang>/runs/` should contain only first-class long-cycle task runs
2. every run directory should be self-describing via metadata files
3. runs should be referentially linked by manifests, not by directory nesting
4. raw artifacts and aggregate exports should be clearly separated inside a run
5. one task should be able to consume another task's outputs without being physically embedded inside it
6. future English runs or new QA specs should not force regenerating unrelated policy/help-gate runs


## 2.1 Compatibility Assumption

For the current phase, we assume:

- there is no requirement to preserve read compatibility with old on-disk runs
- there is no requirement to keep old writer behavior alive
- existing experimental outputs may be discarded or manually regenerated

This is an important simplification.

It means we do not need to carry legacy complexity such as:

- dual-layout readers
- compatibility shims
- transitional path fallbacks
- one-time migration scripts as a required prerequisite

Instead, we can treat this as a clean layout reset and optimize for the new architecture directly.


## 3. Canonical Mental Model

The right top-level object is:

- a `run` is a single execution lineage of one task family

Examples of task families:

- `qa_corpus`
- `policy_records`
- `help_gate_augment`
- future `recall_derive`
- future `reasoning_compress`

This means a run ID should not mean only "one folder under `runs/`."

It should mean:

- one task family
- one spec/config version
- one output bundle


## 4. Recommended Top-Level Layout

Recommended shape:

```text
output/
  shared/
    runs/
      policy_records--pr-1/
  zh/
    runs/
      qa_corpus--ds-2/
      qa_corpus--dsv4pro/
      help_gate_augment--hg-1/
  en/
    runs/
      qa_corpus--en-qa-1/
```

Important principle:

- every directory directly under `output/<lang>/runs/` is one first-class run
- language-agnostic semantic runs may live under `output/shared/runs/`

No run should contain another independent run as a nested subtree.

Recommended placement rule:

- language-bound runs go under `output/<lang>/runs/`
- language-agnostic runs go under `output/shared/runs/`

Examples:

- QA corpora are usually language-bound
- policy records may initially be language-agnostic
- later text-realized policy variants may become language-bound

Simplification enabled by the compatibility assumption:

- we can rename run roots immediately instead of aliasing old names
- we can introduce `shared/` immediately instead of staging it later
- we can stop writing nested `derived/` directories in one pass


## 5. Run Naming Convention

Recommended naming pattern:

- `<task_family>--<run_id>`

Examples:

- `qa_corpus--ds-2`
- `policy_records--pr-1`
- `help_gate_augment--hg-1`

Why this is better:

- the directory name is self-describing before opening metadata
- different task families no longer compete for the same `run_id` namespace
- a consumer can immediately tell whether a run is QA, policy, or composed data

Alternative:

- keep opaque directory names but require `task_family` in `run.json`

This is workable, but less readable on disk.

Recommended preference:

- use explicit directory prefixes


## 6. Internal Run Layout

Every run should have the same broad internal categories.

Recommended shape:

```text
<task_family>--<run_id>/
  run.json
  config.json
  lineage.json
  manifest.json
  work/
  artifacts/
  views/
  system/
```

### `run.json`

Identity and provenance:

- `task_family`
- `run_id`
- `run_name`
- `language`
- `language_scope`
- `created_at`
- `status`
- `schema_version`
- `spec_version`
- `produces`

Simplification enabled by the compatibility assumption:

- `run.json` can become the single canonical run identity file immediately
- we do not need to preserve old `run.json` shapes or partial metadata contracts

### `config.json`

Task-local execution config:

- model names if any
- seed
- sampler profile
- quota settings

### `lineage.json`

Declared upstream references:

- source run references
- filtering conditions
- adapter mode

### `manifest.json`

Counts and inventory:

- item counts
- shard/file list
- key output files
- success/failure counts

### `work/`

Task-local working state:

- checkpoints
- resumable cursors
- temporary task-internal progress files

Simplification enabled by the compatibility assumption:

- old hidden checkpoint names do not need to be preserved
- we can rename `.meta_checkpoint.json` and `.run-state.json` into clearer canonical locations

### `artifacts/`

Task-internal fine-grained files.

Examples:

- per-domain QA trees
- per-item policy records
- composition artifacts

### `views/`

Aggregate exported views.

Examples:

- merged JSONL
- per-domain JSONL
- protocol-ready exports
- text projections

### `system/`

Run-local system metadata:

- failure summaries
- execution logs
- compatibility reports

Since there is no backward-compatibility burden, `system/` does not need to store legacy migration metadata unless we later decide it is useful for debugging.


## 7. Task-Specific Internal Shapes

The broad categories should be shared, but the artifact shape inside each run may differ.

### QA corpus run

Recommended shape:

```text
qa_corpus--ds-2/
  run.json
  config.json
  lineage.json
  manifest.json
  work/
    domains/
      agricultural_sciences/
      archaeology_and_anthropology/
      ...
  artifacts/
    catalog/
    questions/
    answers/
  views/
    qa_export_sft_v1/
      manifest.json
      dataset.jsonl
      domains/
        agricultural_sciences.jsonl
        ...
  system/
    failures.jsonl
    meta_checkpoint.json
```

This fixes the current mixing by moving:

- domain workspaces under `work/domains/`
- task-native raw content under `artifacts/`
- training-oriented projections under `views/`
- operational logs/checkpoints under `system/`

Simplification enabled by the compatibility assumption:

- we do not need to preserve the old "domain directories directly under run root" layout
- QA code can directly target `work/domains/` and `views/qa_export_sft_v1/`

### Policy records run

Recommended shape:

```text
policy_records--pr-1/
  run.json
  config.json
  lineage.json
  manifest.json
  work/
    run_state.json
  artifacts/
    items/
      policy_rec__000001.json
      ...
  views/
    export.jsonl
  system/
    failures.jsonl
```

This makes it explicit that policy records are their own run, not a subproduct of one QA run.

Simplification enabled by the compatibility assumption:

- `policy_records` can be moved to `output/shared/runs/` immediately
- no special-case nested writer path is needed

### Help-gate augment run

Recommended shape:

```text
help_gate_augment--hg-1/
  run.json
  config.json
  lineage.json
  manifest.json
  work/
    run_state.json
  artifacts/
    items/
    preflight/
      composition_preflight.json
  views/
    dataset.jsonl
    protocol.jsonl
  system/
    failures.jsonl
```


## 8. Cross-Run Referencing

The right way to connect runs is through explicit references, not nesting.

Recommended fields in `lineage.json`:

```json
{
  "sources": [
    {
      "task_family": "qa_corpus",
      "run_id": "ds-2",
      "path": "output/zh/runs/qa_corpus--ds-2",
      "use": "payload_adapter"
    },
    {
      "task_family": "policy_records",
      "run_id": "pr-1",
      "path": "output/shared/runs/policy_records--pr-1",
      "use": "policy_source"
    }
  ]
}
```

Important principle:

- a downstream run may depend on many upstream runs
- therefore no single upstream run should be treated as the physical parent directory

Recommended future addition:

- define a stable `artifact_ref` format rather than using directory names as implicit keys

For example:

```text
qa_corpus:ds-2:view:qa_export_sft_v1
policy_records:pr-1:artifact:items
```

This is especially important for:

- one help-gate run consuming one policy run plus one QA run
- later reusing the same policy run with a new English QA run
- later reusing the same QA run with a new policy sampler version

Since we do not need legacy compatibility, all new downstream tasks can require explicit lineage from day one.


## 9. Work vs Artifact vs View

The current layout blurs working state, raw semantic truth, and exported projections.

We should make the distinction explicit:

- `work/` stores in-progress operational state
- `artifacts/` stores task-native semantic truth
- `views/` stores externalized projections or merged summaries

For QA:

- domain workspaces and resumable progress belong to `work/`
- structured QA artifacts belong to `artifacts/`
- merged dataset JSONL is a `view`

For policy records:

- item JSON files are artifacts
- merged JSONL is a view

For help-gate:

- composed semantic records are artifacts
- final training JSONL or protocol JSONL are views

Simplification enabled by the compatibility assumption:

- we can remove the `derived/` category entirely instead of trying to reinterpret it
- every task writes directly into the canonical `work / artifacts / views / system` shape


## 10. Metadata Principles

Every first-class run should be self-describing without relying on parent directories.

Minimum required metadata:

- `task_family`
- `run_id`
- `language`
- `language_scope`
- `created_at`
- `schema_version`
- `status`
- `produces`
- `output_summary`

Important rule:

- if a run is copied elsewhere, it should still explain itself

This is another reason nested dependent layouts are brittle.


## 10.1 Task Main Structure

The output-layout refactor works best when each long-cycle task has its own thin entrypoint.

Recommended pattern:

- `qa_main.py`
- `policy_records_main.py`
- `help_gate_main.py`

These task mains should:

- own task-specific CLI parsing
- own task-specific orchestration
- stay thin

Shared modules should provide:

- path resolution
- storage helpers
- metadata writing
- payload adapters
- exporters
- schema models

Important principle:

- do not force all tasks through one giant universal CLI
- do not duplicate shared implementation in each task main

The right balance is:

- task-specific entrypoints
- shared implementation modules

Since there is no requirement to preserve older metadata contracts, we should standardize these fields before further implementation rather than layering them in later.


## 11. Migration Strategy

Because there is no requirement to preserve old runs, this is not really a migration problem.

It is primarily a writer and layout reset problem.

Recommended approach:

### Stage 1: freeze the new canonical layout

Finalize:

- top-level run naming
- run metadata schema
- lineage schema
- `work / artifacts / views / system` contract

### Stage 2: switch all writers directly

Update:

- QA writer paths
- exporter paths
- derived/policy/help-gate writer paths
- path-resolution helpers

so they emit only the new layout.

### Stage 3: regenerate fresh outputs as needed

If older experimental outputs are still useful for reference, they can simply remain outside the supported contract or be deleted and regenerated.

No migration utility is required unless later convenience work makes one worthwhile.


## 12. Concrete Migration Mapping for Current Data

If we choose to preserve current experimental data at all, the recommended conceptual mapping is:

### Existing QA run

- `output/zh/runs/ds-2`
- move or reinterpret as `output/zh/runs/qa_corpus--ds-2`

Internal reshaping:

- domain directories -> `work/domains/`
- `exports/` -> `views/qa_export_sft_v1/`
- `.meta_checkpoint.json` -> `system/meta_checkpoint.json`
- `run.json` stays at top level

### Existing policy run

- `output/zh/runs/ds-2/derived/policy_records`
- becomes `output/shared/runs/policy_records--pr-1`

Metadata should record:

- this run was produced from a standalone policy generator
- it does not require a QA parent
- it is currently language-agnostic unless later text realization is added

### Existing help-gate preflight

- `output/zh/runs/ds-2/derived/help_gate_augment`
- becomes `output/zh/runs/help_gate_augment--hg-1`

Its `lineage.json` should reference:

- `qa_corpus--ds-2`
- `policy_records--pr-1`

Since there is no compatibility burden, this section is illustrative only.

Implementation does not need to physically transform these old directories.

It may be simpler to:

- delete old experimental outputs
- change writers
- regenerate fresh outputs under the new structure


## 13. Code Impact

This refactor will require changing path assumptions in multiple places, but it is simpler without compatibility support.

Important current assumptions:

- `main.py` writes a QA run directly under `output/<lang>/runs/<run_id>`
- `derive.py` currently treats `out_base` as one QA run root and writes `out_base/derived/...`
- `QAPayloadAdapter` assumes `exports/` lives inside the selected QA run
- `DerivedStorageManager` assumes a nested `derived/<task>/` subtree

Recommended code direction:

- centralize run-root resolution
- resolve paths by `task_family` and `run_id`
- teach downstream tasks to declare input run references explicitly
- separate sample IDs from run IDs
- stop treating domain directory names as stable semantic identifiers

This suggests a small shared path module later, for example:

```python
resolve_run_dir(scope, language, task_family, run_id) -> Path
```

And eventually:

```python
make_artifact_ref(task_family, run_id, view_or_artifact, name) -> str
```

Simplification enabled by the compatibility assumption:

- we do not need fallback path probing
- we do not need mixed old/new path readers
- we can rename existing path helpers aggressively
- tests only need to validate the new layout contract


## 14. Recommended First Implementation Order

1. define the new run-root conventions in code and docs
2. add a shared path-resolution layer
3. move QA writers to the new run-root and internal layout
4. move policy/help-gate writers to first-class sibling run directories
5. add explicit `lineage.json` references for downstream tasks
6. regenerate fresh outputs under the new structure

Why this order:

- it solves the worst orthogonality error first
- it removes all nested-run ambiguity early
- it avoids spending time on transitional compatibility machinery


## 15. Open Questions

- should `task_family` be encoded in the directory name, or only in `run.json`?
- should `exports/manifest.json` remain task-specific, or should run-level `manifest.json` always summarize exports too?
- should `run.json` and `config.json` stay separate, or should some small runs inline config into `run.json`?
- do we want one global index later, such as `output/<lang>/runs/index.json`, or is per-run metadata enough for now?


## 15.1 Simplifications We Should Explicitly Take

Because we do not need backward compatibility, we should deliberately take these simplifications:

1. remove the nested `derived/` concept entirely from all new code
2. stop using bare `run_id` directories for new writes
3. require explicit `task_family` in both path and metadata
4. require explicit `lineage.json` for downstream tasks from the start
5. require `views/` instead of the older `exports/` naming for all new writers
6. regenerate fresh outputs instead of writing migration code

These are not just acceptable shortcuts.

They are the cleaner architecture under the current constraints.


## 16. Success Criteria

The refactor is successful if:

- `output/<lang>/runs/` contains only first-class task runs
- orthogonal tasks are no longer physically nested under QA runs
- raw artifacts and export views are clearly separated
- each run is self-describing through metadata
- downstream tasks reference upstream runs explicitly instead of inheriting parent directories
- the same policy run can be reused with multiple QA runs and vice versa
