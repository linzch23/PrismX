from __future__ import annotations

from typing import Any

from .tree_memory import TreeMemoryItem


TREE_TO_KNOWLEDGE_CATEGORY = {
    "conclusion": "research",
    "decision": "decisions",
    "constraint": "constraints",
    "todo": "open_tasks",
    "finding": "cases",
    "hypothesis": "research",
    "discarded_option": "decisions",
}

TREE_TO_LONG_TERM_TYPE = {
    "conclusion": "project",
    "decision": "project",
    "constraint": "project",
    "todo": "project",
    "finding": "project",
    "fact": "project",
    "hypothesis": "project",
    "discarded_option": "project",
}


class KnowledgeCompiler:
    """Compile stable Tree Memory items into long-term memory operations."""

    def compile_tree_memory(
        self,
        items: list[TreeMemoryItem],
        *,
        session_uri: str,
    ) -> list[dict[str, Any]]:
        operations = []
        for item in items:
            category = TREE_TO_KNOWLEDGE_CATEGORY.get(item.memory_type, "cases")
            operations.append(
                {
                    "action": "upsert",
                    "category": category,
                    "type": TREE_TO_LONG_TERM_TYPE.get(item.memory_type, "project"),
                    "source_tree_id": item.tree_id,
                    "source_memory_id": item.id,
                    "key": _key(item),
                    "title": item.title,
                    "abstract": item.content[:180],
                    "overview": item.content,
                    "content": _content(item),
                    "reason": (
                        "Tree Memory promoted because it is stable, highly trusted, "
                        "or repeatedly reused inside the session tree."
                    ),
                    "trust_score": item.confidence,
                    "tags": sorted(set(item.tags + ["tree-memory", item.memory_type])),
                    "links": [
                        {
                            "target_uri": item.uri,
                            "relation": "derived_from",
                            "confidence": 0.95,
                            "reason": f"promoted from Tree Memory during {session_uri}",
                        }
                    ],
                }
            )
        return operations


def _key(item: TreeMemoryItem) -> str:
    return f"{item.tree_id}-{item.memory_type}-{item.id}"


def _content(item: TreeMemoryItem) -> str:
    return "\n".join(
        [
            item.content,
            "",
            "## Tree Memory Source",
            f"- tree_id: {item.tree_id}",
            f"- source_session_id: {item.source_session_id or '(unknown)'}",
            f"- source_branch: {item.source_branch or '(unknown)'}",
            f"- source_entry_id: {item.source_entry_id or '(unknown)'}",
            f"- reuse_count: {item.reuse_count}",
        ]
    )
