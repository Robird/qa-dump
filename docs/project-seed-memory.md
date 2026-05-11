# Project Seed Memory

This file is the external memory for future sessions. It is intended to restore the project's state, design logic, and near-term direction quickly after context loss.


## 1. What This Project Is

`qa-dump` started as a pipeline for generating a broad QA dataset by:

1. discovering top-level domains
2. building a knowledge tree per domain
3. generating questions at leaf nodes
4. generating answers
5. exporting a unified JSONL dataset

But the project direction has expanded. The current vision is:

- use broad QA data as the first substrate
- derive better structured supervision from it
- support curriculum-aware SFT for small open-weight base LLMs
- later extend toward Sim-Psych style data:
  stimulus -> appraisal -> state shift -> intent -> response
- align future datasets with an agentic context protocol rather than flat prompt strings

In short:

- first build raw knowledge
- then build structured derived data
- then explore richer personality / agent training


## 2. Current Concrete Status

### 2.1 Raw QA dataset exists

The first major raw QA run is complete at:

- [output/zh/runs/ds-2/exports/manifest.json](/repos/qa-dump/output/zh/runs/ds-2/exports/manifest.json)
- [output/zh/runs/ds-2/exports/dataset.jsonl](/repos/qa-dump/output/zh/runs/ds-2/exports/dataset.jsonl)

Key facts from `ds-2`:

- `run_id`: `ds-2`
- language: `zh`
- `questions_per_node`: `10`
- `max_workers`: `16`
- total records: `101698`
- exported domain files: `19`

This is the first real substrate for downstream experiments.

### 2.2 Another run exists but appears exploratory / partial

There is also:

- [output/zh/runs/dsv4pro/run.json](/repos/qa-dump/output/zh/runs/dsv4pro/run.json)

This run should be treated as secondary context unless a future session confirms its completeness and consistency.

### 2.3 Domain checkpoint count

At the time this memory file was written, there were `22` `.checkpoint.json` files under `output/zh/runs/`.

### 2.4 Runtime environment

The active development environment is expected to have these variables set:

- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_API_KEY`

Treat the pipeline as runnable against the live DeepSeek API by default.

Implication:

- when validating QA generation or other real task flows, prefer actual end-to-end execution when it is useful
- do not assume the repo is limited to mock-only or dry-run-only development


## 3. The Most Important Design Decisions So Far

### 3.1 Treat the project as a curriculum-aware data factory

Do not think only in terms of a flat QA corpus.

The intended growth path is:

1. raw QA
2. Bloom-aware augmentation
3. recall extraction
4. reasoning compression
5. later calibration / Sim-Psych / agentic targets

### 3.2 Preserve semantic truth, not only prompt text

This became a major principle after reading external agentic format work.

Important rule:

- do not treat the final stitched prompt string as the only source of truth
- preserve a semantic record first
- later project it into protocol-specific or text-specific formats

This matters for future:

- `observation / belief / me` formatting
- loss masking
- structured tool / reasoning targets
- Sim-Psych data

### 3.3 Two-phase Sim-Psych strategy

Sim-Psych was intentionally split into two phases:

1. generate a rich dataset of stimuli
2. later generate ideal responses

Reason:

- first we need enough “fire and acid” applied to the character
- only then can we meaningfully design arc, recovery, and ideal response

### 3.4 Single personality prototype + state conditioning

Do not pursue many personas first.

Current direction:

- one stable personality base
- many states / conditions / situations

Working personality idea:

- youthful but educated inner posture
- knows much, lacks lived social experience
- sincere, brave, upward-looking
- believes in love, effort, truthfulness, self-cultivation
- should not collapse into cynicism

The right mental model is:

- “I remain myself, but my state changes under different circumstances.”


## 4. Derived-Data Workstreams Already Planned

These are the first explicit post-processing tasks:

### 4.1 Shared foundation

- source discovery
- task-local checkpoints
- resumable execution
- coarse-grained worker parallelism
- structured parsing
- manifests / exports
- semantic export and protocol projection hooks

Doc:

- [docs/plans/shared-derived-data-foundation.md](/repos/qa-dump/docs/plans/shared-derived-data-foundation.md)

### 4.2 BloomAugmentTask

Generate lower-Bloom companion questions from higher-Bloom source questions.

This is intentionally the first implementation target because it is:

- useful
- close to the current QA pipeline
- relatively easy to validate

Doc:

- [docs/plans/bloom-augment-task.md](/repos/qa-dump/docs/plans/bloom-augment-task.md)

### 4.3 RecallDeriveTask

Derive concise `knowledge_recall` targets from existing QA artifacts.

This is important because:

- small models may learn recall better than long reasoning
- `question -> recall -> answer` is a strong early SFT target
- it also aligns naturally with future agentic `me` outputs

Doc:

- [docs/plans/recall-derive-task.md](/repos/qa-dump/docs/plans/recall-derive-task.md)

### 4.4 ReasoningCompressTask

Turn raw reasoning into compact structured supervision.

Important split:

- `clean_path`: short successful reasoning
- `repair_path`: local error detection / rollback / correction

Key lesson:

- do not train only happy-path reasoning
- recovery primitives matter

Doc:

- [docs/plans/reasoning-compress-task.md](/repos/qa-dump/docs/plans/reasoning-compress-task.md)


## 5. Core Docs and What They Mean

### 5.1 Main roadmap

- [docs/research-roadmap.md](/repos/qa-dump/docs/research-roadmap.md)

Use this for:

- overall project direction
- priority workstreams
- curriculum strategy
- interpretability and evaluation ideas

### 5.2 Sim-Psych theory seed

- [docs/idea/sim-psych.md](/repos/qa-dump/docs/idea/sim-psych.md)

Use this for:

- stimulus ontology
- appraisal-based design thinking
- cross-disciplinary inspiration

### 5.3 Sim-Psych Q&A summary

- [docs/idea/sim-psych-qa.md](/repos/qa-dump/docs/idea/sim-psych-qa.md)

Use this for:

- the clearest high-level explanation of current Sim-Psych thinking
- two-stage decomposition
- personality stance
- why this work matters

### 5.4 Sim-Psych x agentic protocol notes

- [docs/idea/sim-psych-agentic-format-notes.md](/repos/qa-dump/docs/idea/sim-psych-agentic-format-notes.md)

Use this for:

- how QA and Sim-Psych data map into `observation / belief / me`
- why semantic truth should precede text projection
- why derived data should be protocol-aware

### 5.5 Learning map / related work

- [docs/idea/learning-map.md](/repos/qa-dump/docs/idea/learning-map.md)

Use this for:

- which related work is most relevant
- what to read first if time is scarce
- curriculum / LoRA / merge / adapter ideas
- what to borrow vs what not to over-copy


## 6. Important External Influence

Two external documents strongly influenced later thinking:

- `/mnt/fast/LLM/study-sft/examples/agentic-ml/01-ask-and-answer.txt`
- `/mnt/fast/LLM/study-sft/docs/agentic-context-format-design.md`

Key takeaway from them:

- the future training target may not be plain `system / user / assistant`
- instead, we may want a protocol centered on:
  - `observation`
  - `belief`
  - `me`
- therefore our data pipeline should eventually produce semantic records that can be projected into that protocol


## 7. Suggested Recovery Order for a New Session

If a future session needs to rehydrate context quickly, read in this order:

1. this file
2. [docs/research-roadmap.md](/repos/qa-dump/docs/research-roadmap.md)
3. [docs/plans/shared-derived-data-foundation.md](/repos/qa-dump/docs/plans/shared-derived-data-foundation.md)
4. [docs/plans/bloom-augment-task.md](/repos/qa-dump/docs/plans/bloom-augment-task.md)
5. [docs/plans/recall-derive-task.md](/repos/qa-dump/docs/plans/recall-derive-task.md)
6. [docs/idea/sim-psych-qa.md](/repos/qa-dump/docs/idea/sim-psych-qa.md)
7. [docs/idea/sim-psych-agentic-format-notes.md](/repos/qa-dump/docs/idea/sim-psych-agentic-format-notes.md)
8. [docs/idea/learning-map.md](/repos/qa-dump/docs/idea/learning-map.md)


## 8. Most Likely Next Steps

If continuing from the current point, likely good next steps are:

1. inspect the raw `ds-2` dataset and verify data quality / domain balance
2. implement the shared derived-data framework
3. build `BloomAugmentTask` first
4. then build `RecallDeriveTask`
5. run a very small SFT experiment on:
   `question -> answer`
   vs
   `question -> recall -> answer`
6. only after that, begin implementing richer Sim-Psych task schemas

The principle is:

- prove the main pipeline works
- then spend resources on richer personality / agent behavior targets


## 9. Community / Collaboration Direction

A new idea emerged late in the session:

- community participation could help with data creation
- public contribution formats could allow others to submit:
  - question cards
  - stimulus cards
  - appraisal cards
  - response cards

Important caution:

- public forums should be treated as recruitment / discussion frontends
- the repo should remain the source of formal schema, validation rules, and canonical data

This idea was not yet implemented, only discussed as a promising future direction.


## 10. Open Technical Questions Still Alive

Some unresolved but important questions:

- how much long reasoning can small base models absorb before it becomes noise?
- when should easy tasks give way to medium / hard tasks in curriculum SFT?
- should unrelated simple tasks be mixed or staged?
- how much of reasoning should be semantic structure vs prose?
- can adapter merging help on a low-resource setup, or should modular routing be preferred?
- how should Sim-Psych state variables be defined compactly enough for real training?


## 11. If Starting Fresh With Very Little Time

The shortest path to useful progress is:

1. use `ds-2`
2. derive a small `remember` + `recall` subset
3. train a tiny first-pass SFT baseline
4. check whether `recall` supervision helps more than plain QA

This is the most practical “does the idea work at all?” test.


## 12. One-Sentence Project Motto

First let the model truly encounter the world, then help it learn how to respond to the world without losing truthfulness, courage, and the capacity to grow.
