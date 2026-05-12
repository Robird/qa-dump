import logging
from collections import deque
from typing import Optional

from api import LLMClient
from models import (
    CategoryListResponse,
    Checkpoint,
    KnowledgeNode,
    KnowledgeTree,
    Phase,
    get_node_by_path,
    to_slug,
)
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
            queue = deque(tuple(p) for p in self.checkpoint.catalog_frontier)
        else:
            root = self._discover_root(seed_domain)
            tree = KnowledgeTree(domain=seed_domain, root=root)
            queue: deque[tuple[str, ...]] = deque()
            for child in root.children:
                queue.append((child.slug,))
            self._persist(tree, queue)
            self.storage.write_node([], root)

        while queue:
            path = queue.popleft()
            path_str = "/".join(path)

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

            node_segments = list(path)
            self.storage.write_node(node_segments, node)
            self._persist(tree, queue)

        self.storage.save_catalog(tree)
        return tree

    def _discover_root(self, domain: str) -> KnowledgeNode:
        messages = [
            {"role": "system", "content": self.p["root_system"]},
            {"role": "user", "content": self.p["root_user"].format(domain=domain)},
        ]
        result = self.llm.chat_structured(
            messages,
            output_model=CategoryListResponse,
            tool_name="submit_root_categories",
            tool_description="Submit the root-level domain categories for the requested knowledge tree.",
            temperature=0.3,
        )
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
        result = self.llm.chat_structured(
            messages,
            output_model=CategoryListResponse,
            tool_name="submit_child_categories",
            tool_description="Submit the child categories for the requested knowledge topic.",
            temperature=0.3,
        )
        return self._parse_categories(result)

    @staticmethod
    def _parse_categories(result: CategoryListResponse) -> list[KnowledgeNode]:
        nodes = []
        for item in result.categories:
            slug = item.slug or to_slug(item.name or "untitled")
            nodes.append(KnowledgeNode(
                name=item.name or "Untitled",
                slug=slug,
                description=item.description,
            ))
        return nodes

    def _persist(self, tree: KnowledgeTree, queue: deque) -> None:
        cp = Checkpoint(
            phase=Phase.CATALOG_DISCOVERY,
            knowledge_tree=tree,
            catalog_frontier=[list(p) for p in queue],
        )
        self.storage.save_checkpoint(cp)
