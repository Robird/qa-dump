# ReasoningCompressTask Plan

This document defines how to transform raw reasoning logs into compact, structured supervision targets that are more suitable for small models.


## 1. Goal

Turn verbose or noisy reasoning logs into inspectable reasoning data that teaches either:

- how to solve a problem cleanly
- how to notice and repair a local mistake

This task should not simply replay raw hidden-thought-style transcripts.


## 2. Why This Is Hard

A naive summary of successful reasoning only teaches happy paths.

That leaves out important behavior:

- checking an intermediate conclusion
- noticing that a branch is unreliable
- rolling back to a safer state
- deciding to stop and admit uncertainty

If we want robust small models, we need more than polished success traces.


## 3. Two Output Modes

### Clean path

Purpose:

- teach short successful reasoning

Focus:

- recalled facts
- key inference steps
- answer construction

### Repair path

Purpose:

- teach compact recovery behavior

Focus:

- tempting intermediate claim
- verification step
- issue detection
- rollback or revision
- corrected next step

This split should be explicit in the data model.


## 4. Inputs

Possible inputs:

- question
- answer
- raw `reasoning_content`
- derived recall
- source Bloom level
- teacher-agent evaluation

`derived recall` is especially useful because it can anchor compressed reasoning in stable prerequisite facts.


## 5. Clean-Path Output Shape

Suggested format:

```json
{
  "mode": "clean_path",
  "recall": [
    "fact 1"
  ],
  "reasoning": [
    "step 1",
    "step 2"
  ],
  "answer": "..."
}
```

Requirements:

- short
- faithful
- decisive
- no decorative filler


## 6. Repair-Path Output Shape

Suggested format:

```json
{
  "mode": "repair_path",
  "candidate_step": "tempting intermediate claim",
  "verification": "check or counterexample",
  "issue_found": "why the candidate step is unsafe",
  "revised_step": "corrected next step",
  "answer": "..."
}
```

This does not aim to encode the full messy search process. It teaches local recovery primitives.


## 7. Sources of Repair Data

Potential sources:

- raw reasoning logs that naturally contain self-correction
- teacher-generated local mistake variants
- contrastive rewrites of clean-path traces

The first version should not depend on naturally occurring rich failure traces. Those may be rare or too noisy.

Teacher-generated local mistake variants may be a better starting point.


## 8. Prompting Guidance

For clean-path prompts:

- compress to the minimum useful steps
- keep each step atomic
- preserve factual dependency

For repair-path prompts:

- invent or isolate one plausible local mistake
- keep the mistake realistic, not absurd
- show how it is checked
- show how the reasoning returns to a safe path


## 9. Validation Rules

Clean-path validation:

- steps are ordered
- steps are short
- final answer matches source answer
- no obvious unsupported leap

Repair-path validation:

- candidate step is plausible
- issue is clearly stated
- revised step addresses the issue
- final answer is preserved or uncertainty is stated honestly


## 10. Small-Model Design Principle

Do not teach sprawling search traces first.

For small models, prioritize:

- short successful traces
- compact local repair traces
- explicit uncertainty when recovery is incomplete

This is more likely to produce robust behavior than imitating long wandering transcripts.


## 11. Open Questions

- Should repair-path examples always end in the final correct answer?
- When should a repair-path sample end with honest abstention instead?
- How many reasoning steps are too many for a small-model-friendly target?
- Should clean-path and repair-path data be mixed or staged?


## 12. Recommended First Version

1. implement clean-path compression first
2. require very short step lists
3. use derived recall when available
4. design repair-path format in parallel
5. only then add teacher-generated local mistake variants


## 13. Success Criteria

The task is successful if:

- clean-path data is clearly shorter and cleaner than raw reasoning logs
- repair-path data teaches detectable recovery behavior
- outputs remain inspectable by humans
- the resulting targets are plausible for small-model SFT
