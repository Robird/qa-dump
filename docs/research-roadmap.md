# QA-Dump Research Roadmap

This document captures the medium-term research and product direction for turning the current QA generation pipeline into a curriculum-aware training data factory for small open-weight base LLMs.

The core mindset is simple:

- We are not only generating samples.
- We are designing a growth path.
- The target is not just "better answers", but a model that can recall, reason, calibrate, and keep learning.


## 1. Current Strengths

The current pipeline already gives us a strong base:

- hierarchical domain coverage
- explicit leaf-node question generation
- `bloom_level` labels
- model answers
- logged `reasoning_content`
- resumable checkpoints and exportable datasets

This is unusually valuable because it gives us structure at both the content level and the process level.


## 2. Main Direction

We should treat the dataset as a staged curriculum rather than a flat pile of SFT samples.

The intended learning path is:

1. `remember`: memorize and reliably recall core facts
2. `understand`: explain, paraphrase, compare, classify
3. `apply`: use recalled knowledge in simple tasks
4. `analyze` and above: multi-step reasoning, synthesis, verification, and recovery

The intuition is that small base models may fail not only because tasks are "too hard", but because the training mixture skips too quickly from recall to high-level reasoning.


## 3. From QA Pipeline to Derived-Data Platform

The next step should not be a pile of one-off scripts.

Instead, we should build a shared derived-data framework that can run multiple post-processing tasks over existing QA artifacts. The first wave of tasks is:

1. `BloomAugmentTask`
2. `RecallDeriveTask`
3. `ReasoningCompressTask`

These tasks are structurally similar to the current QA generation flow:

- scan source items
- select pending work via checkpoint
- call an LLM or specialist agent
- parse structured results
- write derived artifacts
- support resume and coarse-grained parallelism

This suggests a reusable batch-processing base layer rather than separate bespoke pipelines.


## 4. Priority Workstreams

### 4.1 Public Foundation

Build shared infrastructure for derived-data tasks:

- item discovery
- task-local checkpointing
- resumable workers
- output layout conventions
- structured request/response parsing
- summary manifests and exports

This is the lowest-level enabler for everything that follows.

### 4.2 BloomAugmentTask

Generate lower-Bloom companion questions from higher-Bloom source questions.

This is the simplest and most immediately useful task because:

- it closely mirrors the current question-generation pipeline
- it directly supports curriculum training
- it can be done in a single top-down pass with minimal duplication

### 4.3 RecallDeriveTask

Derive short knowledge-recall targets from existing answers and reasoning logs.

This gives us a more small-model-friendly supervision target than raw reasoning transcripts.

### 4.4 ReasoningCompressTask

Transform raw reasoning into structured, inspectable, compact supervision targets.

This task should explicitly split into:

- `clean path`: short successful reasoning traces
- `repair path`: local error detection, rollback, and correction traces

This distinction matters because raw successful reasoning alone does not teach recovery behavior.


## 5. Bloom-Level Data Augmentation

### Goal

For each question above `remember`, generate one or two lower-level companion questions.

Examples:

- `analyze` -> add `remember` and `understand`
- `apply` -> add `remember`
- `evaluate` -> add `understand` and `apply`

### Why this may help

- strengthens knowledge recall before demanding difficult reasoning
- creates a curriculum from the same concept neighborhood
- improves sample efficiency by reusing already-generated domain trees
- gives us aligned sample families of increasing difficulty around the same topic

### Practical design

For each original QA sample, possible derived questions include:

- `supporting_facts_question`
- `core_definition_question`
- `simple_explanation_question`

Each derived question should preserve topic locality and target a lower Bloom level.

### Important constraint

Do not let augmentation drift too far away from the source concept. Derived questions should remain in the same local node or direct parent-child neighborhood.


## 6. Curriculum Training Strategy

The dataset should support multiple phases of SFT rather than one mixed run.

Suggested schedule:

1. Phase A: mostly `remember`
2. Phase B: `remember` + `understand`
3. Phase C: add `apply`
4. Phase D: gradually increase harder reasoning tasks

Useful knobs:

- ratio of low vs high Bloom levels
- answer length cap
- reasoning length cap
- topic repetition per epoch
- mixing of synthetic vs human-reviewed data

This should be logged carefully so later capability jumps can be compared against training mixture shifts.


## 7. Reasoning as a Derived Target, Not Raw Log Replay

Raw `reasoning_content` is useful, but should not be treated as a perfect supervision target.

Risks:

- it may be verbose but not faithful
- it may include dead ends that small models imitate poorly
- it may consume output budget before the actual answer
- it may reward style over substance

Recommended derived formats:

1. `question -> recall -> answer`
2. `question -> key facts -> short reasoning -> answer`
3. `question -> uncertainty-aware reasoning -> answer`

For small models, a short "knowledge recall then answer" format may be more useful than long chain-of-thought transcripts.

### Proposed intermediate schema

```json
{
  "question": "...",
  "recall": [
    "fact 1",
    "fact 2"
  ],
  "reasoning": [
    "step 1",
    "step 2"
  ],
  "answer": "..."
}
```

This is easier to inspect, easier to filter, and easier to compress for smaller models.


## 8. Clean Path vs Repair Path

`ReasoningCompressTask` should not only extract happy-path success traces.

If we only teach short successful reasoning, we risk training a model that looks neat when it is right but has no recovery skill when it is wrong.

We should model two different reasoning targets:

### Clean path

Short successful reasoning that highlights:

- recalled facts
- decisive inferences
- answer construction

### Repair path

Local recovery behavior that highlights:

- a tempting but unreliable intermediate conclusion
- a verification step
- detection of the issue
- rollback or revision
- corrected next step

For small models, repair-path data should usually be local and structured. We do not need to teach sprawling messy search traces; we need to teach compact recovery primitives.


## 9. Meta-Cognition and "Knowing When Not To Claim"

One of the most promising directions is to train self-awareness explicitly.

### Core idea

After each answer, the model should estimate its own mastery or confidence, then compare that self-estimate against a teacher evaluation signal.

Possible fields:

- `self_assessed_mastery`
- `self_assessed_confidence`
- `teacher_score`
- `calibration_error`
- `recommended_behavior`

### Why it matters

- reduces hallucination pressure
- supports abstention or partial-answer behavior
- enables better tool use and planning
- creates safer long-lived personal agents

### Desirable behaviors

When uncertain, the model should learn patterns such as:

- "I recall these facts..."
- "I am unsure how to combine them..."
- "I should avoid claiming a full answer."

This is better than forcing confident guessing.


## 10. Dynamic Teacher Agent

Instead of using a fixed offline teacher, we can introduce a dynamic teacher agent that adjusts the next teaching batch based on observed weaknesses.

Teacher responsibilities:

- evaluate recent student outputs
- identify weak domains and weak Bloom levels
- pick next batch composition
- decide whether to review, advance, or remediate
- generate companion recall questions for weak topics
- choose between clean-path and repair-path reasoning practice

This could become a closed-loop learning system:

1. student model answers
2. teacher evaluates
3. curriculum updates
4. next data batch is generated accordingly


## 11. Long-Lived Agent Abilities

For a personal agent that persists over time, two abilities may matter as much as raw intelligence:

- interest-driven exploration
- self-maintenance of internal knowledge state

Future dataset tasks may include:

- "What do I know well vs poorly?"
- "What should I review next?"
- "What topic has likely become outdated?"
- "What should I ask tools or the web to verify?"

This pushes training beyond task completion toward durable autonomous behavior.


## 12. Interpretability and Weight-Difference Research

The curriculum setup may also support interpretability experiments.

Interesting hypotheses:

- capability gains between curriculum phases may correspond to structured weight-difference directions
- some bottlenecks in small models may be visible as failures in internal separation, retrieval, composition, or calibration
- recovery behavior may emerge at a different phase than raw answer accuracy

Potential experiments:

1. save checkpoints after each curriculum phase
2. compare activation differences on shared probe sets
3. compare weight deltas between `recall only`, `recall + clean reasoning`, and `recall + repair reasoning`
4. probe whether mastery calibration appears before or after answer quality improves


## 13. Evaluation Should Match the Curriculum

We should avoid a single average score.

Track at least:

- answer correctness
- recall accuracy
- reasoning faithfulness
- calibration quality
- abstention quality
- recovery behavior after uncertainty
- performance by Bloom level
- performance by domain

Suggested special metrics:

- overconfidence rate
- useful partial-answer rate
- "I do not know" precision
- self-assessment vs teacher-score correlation
- repair success after injected intermediate error


## 14. Near-Term Experiments

These look especially high-value:

### Experiment A: Bloom companion augmentation

Take a subset of higher-level questions and generate paired `remember` and `understand` questions.

Measure:

- training stability
- low-level recall gains
- downstream reasoning gains

### Experiment B: QA vs QA+Recall vs QA+CleanReasoning

Train three small-model variants:

1. `question -> answer`
2. `question -> recall -> answer`
3. `question -> recall -> short reasoning -> answer`

Measure which format helps small models most.

### Experiment C: Repair-path supervision

Add compact local error-detection and correction targets.

Measure:

- recovery after a misleading intermediate conclusion
- overconfidence reduction
- useful partial-answer behavior

### Experiment D: Self-assessment calibration

Add self-rating outputs and teacher scores.

Measure:

- confidence calibration
- hallucination reduction
- abstention quality


## 15. Data Design Principles

When expanding the system, keep these rules:

1. Prefer shared infrastructure over one-off batch scripts.
2. Prefer structured intermediate targets over raw monologues.
3. Prefer local concept augmentation over topic drift.
4. Prefer calibrated partial answers over confident fabrication.
5. Prefer curriculum-aware mixtures over flat sampling.
6. Prefer local recovery primitives over sprawling failure transcripts.
7. Prefer experiments that isolate one mechanism at a time.


## 16. Possible Future Dataset Fields

Useful additions to each sample or sample group:

- `source_bloom_level`
- `target_bloom_level`
- `derived_from_question_id`
- `concept_cluster_id`
- `teacher_score`
- `self_score`
- `abstain_allowed`
- `abstain_expected`
- `uncertainty_span`
- `knowledge_recall`
- `short_reasoning_steps`
- `repair_steps`
- `answer_completeness`


## 17. Recommended Order of Implementation

If we want the highest value with the lowest chaos:

1. finalize planning docs and sample schemas
2. build the shared derived-data framework
3. implement `BloomAugmentTask`
4. implement `RecallDeriveTask`
5. implement `ReasoningCompressTask` clean-path mode
6. prototype `ReasoningCompressTask` repair-path mode
7. build evaluation for calibration and abstention
8. prototype dynamic teacher selection


## 18. Open Questions

Questions worth revisiting before implementation:

- How much long reasoning can a small base model absorb before it becomes noise?
- Should self-assessment be a scalar, a rubric, or natural language?
- Is DPO the right tool for calibration, or is plain supervised regression enough at first?
- How should abstention be rewarded when the model knows part of the answer but not all of it?
- Which curriculum transitions create the biggest gains per token?
- What is the smallest useful repair-path supervision format for small models?


## 19. Planning Docs

The following focused planning docs refine the first implementation wave:

- [Shared Derived-Data Foundation](./plans/shared-derived-data-foundation.md)
- [BloomAugmentTask Plan](./plans/bloom-augment-task.md)
- [RecallDeriveTask Plan](./plans/recall-derive-task.md)
- [ReasoningCompressTask Plan](./plans/reasoning-compress-task.md)


## 20. Summary

The long-term opportunity is not merely to train a model that answers questions.

It is to train a model that:

- remembers before it reasons
- reasons from recalled knowledge rather than bluffing
- can recover locally when a promising path goes wrong
- knows when it is uncertain
- asks for help or abstains when appropriate
- can keep learning over time

That is a much more interesting target than ordinary SFT, and the current QA-Dump pipeline is already a strong foundation for it.
