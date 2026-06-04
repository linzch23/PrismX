from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


LONG_TERM_SPECIAL_MEMORY_TYPES = {
    "user_profile",
    "user_feedback",
    "project_state",
    "reference",
}

LONG_TERM_SPECIAL_CATEGORY_MAP = {
    "user_profile": "profile",
    "user_feedback": "preferences",
    "project_state": "events",
    "reference": "research",
}


@dataclass
class TgmRecallResult:
    layer: str
    uri: str
    title: str
    summary: str
    trust_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class TgmContextGateway:
    """Unified access to Tree Memory and long-term knowledge."""

    def __init__(
        self,
        *,
        memory_store: Any,
        tree_memory: Any,
        tree_id_provider,
        active_session_provider=None,
        active_branch_provider=None,
    ) -> None:
        self.memory_store = memory_store
        self.tree_memory = tree_memory
        self.tree_id_provider = tree_id_provider
        self.active_session_provider = active_session_provider
        self.active_branch_provider = active_branch_provider

    @property
    def tree_id(self) -> str:
        return str(self.tree_id_provider())

    @property
    def active_branch_id(self) -> str:
        if self.active_branch_provider is None:
            return ""
        return str(self.active_branch_provider() or "")

    @property
    def active_session_id(self) -> str:
        if self.active_session_provider is None:
            return ""
        return str(self.active_session_provider() or "")

    def remember(
        self,
        note: str,
        *,
        category: str = "events",
        title: str | None = None,
        scope: str = "tree",
        memory_type: str | None = None,
    ) -> str:
        long_term_category = _long_term_category(category, memory_type)
        tree_uri = self.tree_memory.remember(
            self.tree_id,
            note,
            title=title,
            memory_type=_tree_type_for_remember(category, memory_type),
            tags=_tree_tags_for_remember(category, memory_type),
            source_session_id=self.active_session_id,
            source_branch=self.active_branch_id,
            metadata=_tree_metadata_for_remember(category, memory_type, scope),
        )
        if scope == "long_term" or long_term_category:
            source_memory_id = _tree_memory_id_from_uri(tree_uri)
            long_uri = self.memory_store.remember_note(
                note,
                category=long_term_category or category,
                title=title,
                source_tree_id=self.tree_id,
                source_memory_id=source_memory_id,
            )
            return f"{tree_uri} + {long_uri}" if tree_uri and long_uri else tree_uri or long_uri
        return tree_uri

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        tree_limit = max(1, limit // 2)
        long_limit = max(1, limit - tree_limit)
        return self.search_tree(query, limit=tree_limit) + self.search_long_term(query, limit=long_limit)

    def search_tree(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return self.tree_memory.search(self.tree_id, query, limit=limit)

    def search_long_term(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return self.memory_store.search_memory(query, limit=limit)

    def read(self, uri: str, *, layer: str = "auto") -> str:
        if uri.startswith("tree://"):
            return self.tree_memory.read(uri, layer=layer)
        return self.memory_store.read_context(uri, layer=layer)

    def list(self, prefix: str = "tree://", *, limit: int = 50) -> list[dict[str, Any]]:
        if prefix.startswith("tree://") or prefix in {"", "tree"}:
            return self.tree_memory.list(self.tree_id, limit=limit)
        return self.memory_store.list_context(prefix=prefix, limit=limit)

    def neighbors(self, uri: str, *, limit: int = 5) -> list[dict[str, Any]]:
        if uri.startswith("tree://"):
            return []
        return self.memory_store.graph_neighbors(uri, limit=limit)


class TgmRuntimeRecallBuilder:
    """Three-layer TGM runtime recall.

    Active Path Retrieval is represented by active_path_summary because raw
    active branch messages already go to the model as messages. Tree Memory and
    Long-term Knowledge are recalled separately to make horizontal and global
    knowledge visible and budgetable.
    """

    def __init__(self, gateway: TgmContextGateway, *, limit: int = 5, max_chars: int = 12000) -> None:
        self.gateway = gateway
        self.limit = limit
        self.max_chars = max_chars
        self.last_results: list[dict[str, Any]] = []

    def build(
        self,
        query: str,
        *,
        active_path_summary: str = "",
        recall_scope: dict[str, Any] | None = None,
    ) -> str:
        tree_results = self.gateway.search_tree(query, limit=self.limit)
        self._promote_stable_tree_memory()
        long_results = self.gateway.search_long_term(query, limit=self.limit)
        long_results = self._rank_long_term(long_results, recall_scope or {})
        self.last_results = tree_results + long_results

        lines = ["## Runtime Recall"]
        if active_path_summary:
            lines.append("\n### Active Path Retrieval")
            lines.append(active_path_summary[:1600])

        if tree_results:
            lines.append("\n### Tree Memory Retrieval")
            for item in tree_results:
                lines.append(_render_result(item, "tree_memory"))

        if long_results:
            lines.append("\n### Long-term Knowledge Retrieval")
            for item in long_results:
                lines.append(_render_result(item, "long_term_l0"))

        if len(lines) == 1:
            return "(No runtime context recalled.)"
        rendered = "\n".join(lines)
        if len(rendered) <= self.max_chars:
            return rendered
        return rendered[: self.max_chars - 80].rstrip() + "\n...[runtime recall truncated]"

    def _rank_long_term(self, results: list[dict[str, Any]], scope: dict[str, Any]) -> list[dict[str, Any]]:
        session_id = scope.get("session_id")
        project = scope.get("project")
        ranked = []
        for index, result in enumerate(results):
            if result.get("status") in {"archived", "quarantine"}:
                continue
            if result.get("sensitivity") in {"sensitive", "internal"}:
                continue
            meta = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
            score = float(result.get("trust_score") or 0.0)
            if meta.get("source_session") == session_id:
                score += 1.5
            if project and meta.get("project") == project:
                score += 1.0
            if str(result.get("uri", "")).startswith("mem://project/"):
                score += 0.5
            item = dict(result)
            item["recall_score"] = score
            ranked.append((score, -index, item))
        ranked.sort(key=lambda pair: (-pair[0], pair[1]))
        return [item for _, _, item in ranked[: self.limit]]

    def _promote_stable_tree_memory(self) -> None:
        tree_memory = self.gateway.tree_memory
        memory_store = self.gateway.memory_store
        if not hasattr(tree_memory, "promotion_candidates") or not hasattr(memory_store, "promote_tree_memory"):
            return
        for item in tree_memory.promotion_candidates(self.gateway.tree_id):
            uri = memory_store.promote_tree_memory(item)
            if uri and hasattr(tree_memory, "mark_promoted"):
                tree_memory.mark_promoted(self.gateway.tree_id, item.id)


def _render_result(item: dict[str, Any], layer: str) -> str:
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    summary = item.get("abstract") or item.get("overview") or ""
    return (
        f"- URI: {item.get('uri', '')}\n"
        f"  Layer: {layer}\n"
        f"  Trust: {item.get('trust_score', '?')}\n"
        f"  Source: {meta.get('scope') or meta.get('source_session') or meta.get('tree_id') or '?'}\n"
        f"  Matched: {item.get('title', '?')}\n"
        f"  Summary: {summary}"
    )


def _category_to_tree_type(category: str) -> str:
    mapping = {
        "decisions": "decision",
        "constraints": "constraint",
        "open_tasks": "todo",
        "research": "finding",
        "cases": "finding",
        "patterns": "conclusion",
    }
    return mapping.get(category, "finding")


def _long_term_category(category: str, memory_type: str | None) -> str:
    if memory_type in LONG_TERM_SPECIAL_MEMORY_TYPES:
        return LONG_TERM_SPECIAL_CATEGORY_MAP[str(memory_type)]
    if category in LONG_TERM_SPECIAL_MEMORY_TYPES:
        return LONG_TERM_SPECIAL_CATEGORY_MAP[category]
    return ""


def _tree_type_for_remember(category: str, memory_type: str | None) -> str:
    if memory_type in LONG_TERM_SPECIAL_MEMORY_TYPES:
        return "finding"
    return memory_type or _category_to_tree_type(category)


def _tree_tags_for_remember(category: str, memory_type: str | None) -> list[str]:
    tags = [category]
    if memory_type and memory_type != category:
        tags.append(memory_type)
    return tags


def _tree_metadata_for_remember(category: str, memory_type: str | None, scope: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"remember_scope": scope}
    if category in LONG_TERM_SPECIAL_MEMORY_TYPES or memory_type in LONG_TERM_SPECIAL_MEMORY_TYPES:
        metadata["long_term_special_type"] = memory_type or category
    return metadata


def _tree_memory_id_from_uri(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1] if uri else ""
