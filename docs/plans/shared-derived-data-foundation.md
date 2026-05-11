# Shared Derived-Data Foundation

This document defines the shared infrastructure for post-processing existing QA-Dump artifacts into new curriculum-oriented training data.


## 1. Purpose

Several upcoming tasks are structurally the same:

- `BloomAugmentTask`
- `RecallDeriveTask`
- `ReasoningCompressTask`

Each task needs to:

- enumerate source items
- skip already-completed work
- resume from checkpoints
- run LLM-backed transformations
- parse structured outputs
- write derived artifacts
- summarize progress and export outputs

Instead of implementing these repeatedly, we should build one shared batch-processing foundation.


## 2. Scope

This foundation should provide:

- source item discovery
- task-local item identity
- task-local checkpoints
- resumable execution
- coarse-grained worker parallelism
- structured prompt execution
- standardized output layout
- summary manifests
- validation hooks
- semantic export and protocol projection hooks

This foundation should not contain task-specific prompting or task-specific output schemas beyond shared wrappers.


## 3. Conceptual Model

Each derived-data task can be modeled as:

1. discover source items
2. map source item -> stable derived item key
3. decide whether item is pending, complete, or invalid
4. invoke task-specific transformer
5. validate result
6. persist outputs
7. record checkpoint state

The framework should own steps 1, 3, 6, and 7, while task plugins should primarily own step 4 and task-specific validation in step 5.


## 4. Desired Interface

Possible future task plugin shape:

```python
class DerivedTask:
    name: str

    def discover_items(self, args) -> list[SourceItem]: ...

    def make_item_key(self, item: SourceItem) -> str: ...

    def build_messages(self, item: SourceItem, context: TaskContext) -> list[dict]: ...

    def parse_result(self, raw: dict, item: SourceItem) -> ParsedResult: ...

    def validate_result(self, result: ParsedResult, item: SourceItem) -> list[str]: ...

    def write_result(self, result: ParsedResult, item: SourceItem, storage) -> None: ...
```

This is only a planning sketch, not a fixed API.

For v1, we should stop earlier and only share the run lifecycle shell:

- run-root setup
- config/lineage/run metadata writes
- compact run-state persistence
- completion/failure manifest updates

Task-local source discovery, item identity, prompt building, export logic,
and validation should remain task-specific until we have at least one more
derived task that really matches the same execution model.


## 5. Source Discovery

The foundation should support at least these source modes:

- scan exported dataset records
- scan per-domain storage directories
- scan task-specific prior outputs

The first implementation should prefer stable on-disk files over in-memory coupling with the live generation pipeline.

Useful source selectors:

- by domain slug
- by Bloom level
- by run ID
- by completeness state
- by derived-task dependency


## 6. Checkpoint and Resume

Each derived task should own its own checkpoint namespace.

Suggested properties:

- source item count
- completed item keys
- failed item keys
- current worker assignment
- run parameters
- timestamps

Important rule:

- task checkpoints must not mutate the original QA generation checkpoints

We want derived-data generation to be resumable without disturbing the base corpus.


## 7. Output Layout

We should use a predictable on-disk layout built around first-class task runs.

Recommended shape:

```text
output/
  shared/
    runs/
      policy_records--pr-1/
  zh/
    runs/
      qa_corpus--qa-1/
      help_gate_augment--hg-1/
```

Each run root should use the same broad categories:

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

Important rules:

- `artifacts/` holds canonical task outputs
- `views/` holds rebuildable projections and exports
- downstream runs reference upstream runs in `lineage.json`; they are not nested physically


## 8. Parallelism Model

We only need coarse-grained parallelism at first.

Preferred approach:

- split by top-level domain or file shard
- one worker process owns one item at a time
- no shared mutable state across workers besides append-safe progress and atomic file writes

This matches the current architecture and keeps failure modes understandable.


## 9. Structured Parsing and Validation

The shared layer should help with:

- JSON mode requests
- normalized parse errors
- retryable vs non-retryable failure categories
- optional schema validation
- logging of content previews on failure

Task-local validation examples:

- Bloom target is lower than source Bloom
- recall items are factual and concise
- reasoning steps are short and ordered


## 10. Dependency Handling

Some tasks depend on outputs from earlier tasks.

Examples:

- `RecallDeriveTask` may depend only on base QA artifacts
- `ReasoningCompressTask` may optionally use derived recall
- future calibration tasks may depend on answer quality scoring

The foundation should support explicit task dependencies but avoid hard-wiring a full DAG scheduler in v1.

For now, simple preflight checks are enough.


## 11. Logging and Exports

Each task should produce:

- per-item artifacts
- aggregate JSONL export
- manifest with counts and configuration
- failure summary

Where practical, exports should distinguish:

- semantic truth records
- protocol-ready projections
- human-readable text projections

The prompt string should not be treated as the only source of truth if the task naturally produces richer structure.

Useful manifest fields:

- source run ID
- task name
- prompt version
- source item count
- completed count
- failed count
- schema version


## 12. Open Questions

- Should source discovery operate from per-domain files or the merged export first?
- How strict should schema validation be in v1?
- Do we want a single generic CLI entrypoint with `--task`, or one script per task?
- How should failed items be retried after prompt changes?


## 13. Recommended First Implementation

1. define shared storage layout
2. define source item model
3. define checkpoint format
4. define task plugin hooks
5. wire one end-to-end derived task through the framework
6. use `BloomAugmentTask` as the first proving ground


## 14. Success Criteria

The foundation is successful if:

- a derived task can run incrementally and resume safely
- multiple tasks can share the same execution skeleton
- failure handling is understandable
- outputs are easy to inspect and export
- later tasks do not need to re-invent orchestration
