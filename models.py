from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Phase(str, Enum):
    CATALOG_DISCOVERY = "catalog_discovery"
    QUESTION_GENERATION = "question_generation"
    ANSWER_GENERATION = "answer_generation"


class KnowledgeNode(BaseModel):
    name: str
    slug: str = ""
    description: str = ""
    children: list[KnowledgeNode] = Field(default_factory=list)
    depth: int = 0

    def is_leaf(self) -> bool:
        return len(self.children) == 0


class KnowledgeTree(BaseModel):
    domain: str
    root: KnowledgeNode


class QuestionItem(BaseModel):
    id: str
    text: str
    bloom_level: str = ""
    node_path: str = ""


class QuestionSet(BaseModel):
    node_path: str = ""
    questions: list[QuestionItem] = Field(default_factory=list)


class AnswerItem(BaseModel):
    question_id: str
    answer: str
    node_path: str = ""


class Checkpoint(BaseModel):
    phase: Phase

    # Phase 1 state
    knowledge_tree: Optional[KnowledgeTree] = None
    bfs_queue: list[list[str]] = Field(default_factory=list)
    completed_nodes: list[str] = Field(default_factory=list)
    current_depth: int = 0

    # Phase 2 state
    leaf_queue: list[str] = Field(default_factory=list)
    questions_done: list[str] = Field(default_factory=list)

    # Phase 3 state
    answer_queue: list[dict] = Field(default_factory=list)
    answers_done: list[str] = Field(default_factory=list)


def to_slug(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9一-鿿\s_-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_") or "untitled"


def get_node_by_path(root: KnowledgeNode, path: list[str]) -> KnowledgeNode:
    node = root
    for segment in path:
        found = next((c for c in node.children if c.slug == segment), None)
        if found is None:
            raise ValueError(f"Path segment '{segment}' not found in node '{node.slug}'")
        node = found
    return node


def collect_leaves(node: KnowledgeNode, prefix: list[str]) -> list[list[str]]:
    if node.is_leaf():
        return [prefix]
    result: list[list[str]] = []
    for child in node.children:
        result.extend(collect_leaves(child, prefix + [child.slug]))
    return result
