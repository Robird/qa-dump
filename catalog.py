import logging
from collections import deque
from typing import Optional

from api import LLMClient
from models import (
    Checkpoint,
    KnowledgeNode,
    KnowledgeTree,
    Phase,
    get_node_by_path,
    to_slug,
)
from prompts import get_prompts
from storage import StorageManager

logger = logging.getLogger(__name__)


class CatalogBuilder:
    def __init__(
        self,
        llm: LLMClient,
        max_depth: int,
        storage: StorageManager,
        prompts: dict,
        checkpoint: Optional[Checkpoint] = None,
    ):
        self.llm = llm
        self.max_depth = max_depth
        self.storage = storage
        self.p = prompts
        self.checkpoint = checkpoint

    def run(self, seed_domain: str) -> KnowledgeTree:
        if self.checkpoint and self.checkpoint.knowledge_tree:
            tree = self.checkpoint.knowledge_tree
            queue = deque(tuple(p) for p in self.checkpoint.bfs_queue)
            completed = set(self.checkpoint.completed_nodes)
        else:
            root = self._discover_root(seed_domain)
            tree = KnowledgeTree(domain=seed_domain, root=root)
            queue: deque[tuple[str, ...]] = deque()
            for child in root.children:
                queue.append((child.slug,))
            completed: set[str] = set()
            self._persist(tree, queue, completed, 0)
            self.storage.write_node([], root)

        while queue:
            path = queue.popleft()
            path_str = "/".join(path)

            if path_str in completed:
                continue

            node = get_node_by_path(tree.root, list(path))
            current_depth = len(path)

            logger.info("Catalog BFS depth=%d node=%s", current_depth, path_str)

            node.depth = current_depth

            if current_depth < self.max_depth:
                children = self._fetch_children(node)
                if children:
                    for child in children:
                        child.depth = current_depth + 1
                        queue.append(path + (child.slug,))
                        child_segments = list(path) + [child.slug]
                        self.storage.write_node(child_segments, child)
                    node.children = children
                else:
                    pass  # node stays as leaf

            completed.add(path_str)
            node_segments = list(path)
            self.storage.write_node(node_segments, node)
            self._persist(tree, queue, completed, current_depth)

        self.storage.save_catalog(tree)
        return tree

    def _discover_root(self, domain: str) -> KnowledgeNode:
        messages = [
            {"role": "system", "content": self.p["root_system"]},
            {"role": "user", "content": self.p["root_user"].format(domain=domain)},
        ]
        result = self.llm.chat_json(messages)
        children = self._parse_categories(result)
        for child in children:
            child.depth = 1
        return KnowledgeNode(
            name=domain,
            slug=to_slug(domain),
            description=f"Root domain: {domain}",
            children=children,
            depth=0,
        )

    def _fetch_children(self, node: KnowledgeNode) -> list[KnowledgeNode]:
        messages = [
            {"role": "system", "content": self.p["expand_system"]},
            {"role": "user", "content": self.p["expand_user"].format(
                name=node.name, description=node.description
            )},
        ]
        result = self.llm.chat_json(messages)
        return self._parse_categories(result)

    @staticmethod
    def _parse_categories(result: dict) -> list[KnowledgeNode]:
        raw = result.get("categories", [])
        nodes = []
        for item in raw:
            slug = item.get("slug", "") or to_slug(item.get("name", "untitled"))
            nodes.append(KnowledgeNode(
                name=item.get("name", "Untitled"),
                slug=slug,
                description=item.get("description", ""),
            ))
        return nodes

    def _persist(
        self, tree: KnowledgeTree, queue: deque, completed: set, depth: int
    ) -> None:
        cp = Checkpoint(
            phase=Phase.CATALOG_DISCOVERY,
            knowledge_tree=tree,
            bfs_queue=[list(p) for p in queue],
            completed_nodes=sorted(completed),
            current_depth=depth,
        )
        self.storage.save_checkpoint(cp)
