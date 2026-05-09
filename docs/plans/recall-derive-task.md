# RecallDeriveTask Plan

This document defines the task of deriving compact knowledge-recall targets from existing QA artifacts.


## 1. Goal

Create a short, explicit recall layer that sits between the raw question and the final answer.

Desired training pattern:

- `question -> recall -> answer`

The intent is to give small models a more learnable intermediate target than long reasoning transcripts.


## 2. Why This Matters

Small models often benefit more from concise retrieval-like supervision than from long chain-of-thought style text.

Recall targets can help:

- strengthen factual retrieval
- stabilize answers
- separate knowledge access from reasoning style
- support staged curriculum learning

They also make good early `me` targets in an agentic training protocol, because `question -> recall -> answer` is a natural bridge between plain QA SFT and richer structured agent behavior.


## 3. Inputs

Each source item may use:

- question text
- answer text
- source Bloom level
- node path
- domain metadata
- raw reasoning log when available

The answer should be the primary grounding source. Raw reasoning is optional helper context, not the authority.


## 4. Outputs

Each derived item should include:

- `derived_from_question_id`
- `knowledge_recall`
- `recall_type`
- `domain_slug`
- `node_path`
- optional `supporting_answer_span`

Suggested `knowledge_recall` format:

- short bullet-like facts
- definition snippets
- formulas
- named principles
- explicit known givens


## 5. Recall Types

Useful recall categories:

- definition recall
- fact recall
- formula recall
- condition recall
- known-givens recall

We do not need all categories in every item.


## 6. Prompting Guidance

The prompt should ask for:

- only facts needed for solving or justifying the answer
- concise atomic statements
- no full reasoning chain
- no speculative claims
- no stylistic filler

Recall should answer the question:

- "What should the model have in working memory before it starts reasoning?"


## 7. Validation Rules

Minimum validation:

- recall is non-empty
- recall is shorter than the answer by default
- recall does not simply repeat the whole answer
- recall items are atomic enough to inspect

Nice-to-have validation:

- teacher checks factual support
- span alignment to answer or source reasoning
- duplicate recall compression


## 8. Relationship to Bloom Levels

Recall targets are especially useful for:

- `remember`
- `understand`
- `apply`

For higher-level questions, recall should still stay at the level of prerequisites, not solution prose.


## 9. Recommended First Output Schema

```json
{
  "derived_from_question_id": "...",
  "knowledge_recall": [
    "fact 1",
    "fact 2"
  ],
  "recall_type": [
    "definition",
    "formula"
  ]
}
```


## 10. Open Questions

- Should recall always be a list, or can it be a short paragraph?
- How many recall items should be allowed?
- Should we require evidence spans in v1?
- Can the same recall record be shared across multiple sibling questions?


## 11. Recommended First Version

1. derive 2 to 5 concise recall items per source QA
2. use answer text as the main anchor
3. allow reasoning logs only as supplementary context
4. export a simple JSONL for `question -> recall -> answer` experiments


## 12. Success Criteria

The task is successful if:

- recall targets are concise and useful
- they improve answer stability for small models
- they are easier to inspect than raw reasoning logs
- they support downstream `ReasoningCompressTask`
