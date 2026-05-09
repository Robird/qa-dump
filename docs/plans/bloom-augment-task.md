# BloomAugmentTask Plan

This document defines the first derived-data task: generating lower-Bloom companion questions from higher-Bloom source questions.


## 1. Goal

For each source question above `remember`, derive one or more lower-level companion questions that stay within the same concept neighborhood.

Examples:

- `apply` -> add `remember`
- `analyze` -> add `remember` and `understand`
- `evaluate` -> add `understand` and `apply`

This task is intended to be the first implementation on top of the shared derived-data foundation.


## 2. Why Start Here

This task is especially attractive because:

- it closely matches the current question-generation pipeline
- the value for curriculum learning is immediate
- the source and target are easy to inspect
- it can be executed in a clean top-down pass
- duplicate generation can be controlled with stable source IDs

This is the lowest-risk way to validate the new framework.


## 3. Inputs

Each source item should include at least:

- source question text
- source answer
- source `bloom_level`
- `question_id`
- `domain_slug`
- `node_path`
- optional reasoning log

The first version should not require reasoning logs.


## 4. Outputs

Each derived record should include:

- `derived_question_id`
- `derived_from_question_id`
- `source_bloom_level`
- `target_bloom_level`
- `question`
- optional `answer`
- `domain_slug`
- `node_path`
- `concept_cluster_id`

There are two viable output modes:

1. question-only augmentation
2. question+answer augmentation

The first mode is cheaper; the second is immediately trainable.


## 5. Core Task Logic

For each eligible source question:

1. inspect source Bloom level
2. choose one or more lower target levels
3. ask the model to derive local companion questions
4. validate that targets are lower-level and on-topic
5. persist outputs

Important constraint:

- derived questions must remain in the same local concept neighborhood

We want curriculum scaffolding, not topic drift.


## 6. Target-Level Policy

Suggested first-pass mapping:

- `understand` -> add `remember`
- `apply` -> add `remember`
- `analyze` -> add `remember`, `understand`
- `evaluate` -> add `understand`, `apply`
- `create` -> add `understand`, `analyze`

This mapping is a starting point, not a final ontology.


## 7. Prompting Guidance

The task prompt should emphasize:

- preserve the topic
- move down in Bloom level
- prefer factual recall and simple explanation
- avoid introducing unrelated subtopics
- produce concise, unambiguous questions

Bad derived sample:

- changes the domain or concept
- asks a much broader or much narrower question than the source
- remains as hard as the original question


## 8. Validation Rules

Minimum validation rules:

- target Bloom level is lower than source
- question text is non-empty
- no exact duplicate of source question
- topic locality appears preserved

Nice-to-have validation:

- lexical overlap heuristic
- node-path consistency heuristic
- teacher-agent review on a sample subset


## 9. Output Granularity

We should decide whether one source question yields:

- exactly one derived question
- one derived question per target level
- one or two derived variants per target level

Recommended v1:

- one derived question per selected target level

This keeps counting, validation, and downstream mixing simpler.


## 10. Open Questions

- Should answers be generated immediately or in a second pass?
- Should source answers be visible to the teacher model during augmentation?
- How much lexical similarity is too much?
- Should target-level selection be rule-based or teacher-selected?


## 11. Recommended First Version

1. select source questions with Bloom level above `remember`
2. derive one lower-level question per selected target level
3. write question-only outputs first
4. add optional answer-generation pass later if needed

This gives us the quickest path to evaluating curriculum usefulness.


## 12. Success Criteria

The task is successful if:

- outputs are local to the original concept
- target levels are consistently simpler
- duplicates remain low
- the resulting dataset supports cleaner staged training mixes
