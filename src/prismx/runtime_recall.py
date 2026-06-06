from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .tree_memory import ContextPacket, RetrievalIntent


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
    """Unified access to Tree Memory and Long-term Knowledge."""

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
        return str(self.active_branch_provider() or "") if self.active_branch_provider else ""

    @property
    def active_session_id(self) -> str:
        return str(self.active_session_provider() or "") if self.active_session_provider else ""

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
            fold_id = _tree_object_id_from_uri(tree_uri)
            fold = self.tree_memory.fold_by_id(self.tree_id, fold_id) if fold_id else None
            long_uri = self.memory_store.remember_note(
                note,
                category=long_term_category or category,
                title=title,
                source_tree_id=self.tree_id,
                source_fold_id=fold_id,
                source_evidence_ids=list(getattr(fold, "evidence_ids", []) or []),
            )
            return f"{tree_uri} + {long_uri}" if tree_uri and long_uri else tree_uri or long_uri
        return tree_uri

    def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return self.search_tree(query, limit=limit) + self.search_long_term(query, limit=limit)

    def search_tree(self, query: str | RetrievalIntent | dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
        if hasattr(self.tree_memory, "retrieve"):
            return self.tree_memory.retrieve(self.tree_id, query, limit=limit)
        return self.tree_memory.search(self.tree_id, str(query), limit=limit)

    def search_long_term(self, query: str | dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
        return self.memory_store.search_memory(query, limit=limit)

    def evidence_snippets(self, evidence_ids: list[str], *, query: str = "", limit_chars: int = 1800) -> list[dict[str, Any]]:
        if not hasattr(self.tree_memory, "snippet"):
            return []
        return self.tree_memory.snippet(self.tree_id, evidence_ids, query=query, limit_chars=limit_chars)

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
    """LLM-first TGM 3.0 runtime recall builder."""

    def __init__(
        self,
        gateway: TgmContextGateway,
        *,
        limit: int = 5,
        max_chars: int = 12000,
        client: Any | None = None,
        model: str = "",
    ) -> None:
        self.gateway = gateway
        self.limit = limit
        self.max_chars = max_chars
        self.client = client
        self.model = model
        self.last_results: list[dict[str, Any]] = []
        self.last_packet: ContextPacket | None = None

    def build(
        self,
        query: str,
        *,
        active_path_summary: str = "",
        recall_scope: dict[str, Any] | None = None,
    ) -> str:
        coarse = self._coarse_reasoning(query, active_path_summary, recall_scope or {})
        if not coarse.get("needs_retrieval", True):
            packet = ContextPacket(
                query=query,
                active_path_summary=active_path_summary,
                coarse_reasoning=str(coarse.get("reason") or ""),
            )
            self.last_results = []
            self.last_packet = packet
            return packet.render(max_chars=self.max_chars)

        intent = self._retrieval_intent(query, active_path_summary, coarse)
        tree_results = self.gateway.search_tree(intent, limit=intent.limit or self.limit)
        snippets = self._evidence_snippets(intent, tree_results)
        self._promote_stable_tree_memory()
        long_results = self.gateway.search_long_term(
            {
                "query": intent.query,
                "keywords": intent.keywords,
                "types": _long_term_types_for_intent(intent),
            },
            limit=self.limit,
        )
        packet = ContextPacket(
            query=query,
            active_path_summary=active_path_summary,
            coarse_reasoning=str(coarse.get("reason") or ""),
            retrieval_intent=intent,
            tree_memory=tree_results,
            evidence_snippets=snippets,
            long_term=long_results,
        )
        self.last_results = tree_results + long_results
        self.last_packet = packet
        return packet.render(max_chars=self.max_chars)

    def _coarse_reasoning(self, query: str, active_path_summary: str, scope: dict[str, Any]) -> dict[str, Any]:
        prompt = {
            "task": "Decide whether PrismX Runtime Recall should retrieve memory.",
            "query": query,
            "active_path_summary": active_path_summary,
            "scope": scope,
            "output_json": {"needs_retrieval": True, "reason": "short reason"},
        }
        data = self._llm_json(prompt, fallback={"needs_retrieval": True, "reason": "Use TGM recall for relevant tree and long-term context."})
        data["needs_retrieval"] = bool(data.get("needs_retrieval", True))
        return data

    def _retrieval_intent(self, query: str, active_path_summary: str, coarse: dict[str, Any]) -> RetrievalIntent:
        prompt = {
            "task": "Create Tree Memory and Long-term Knowledge retrieval intent.",
            "query": query,
            "active_path_summary": active_path_summary,
            "coarse_reasoning": coarse,
            "output_json": {
                "query": query,
                "keywords": ["important words"],
                "node_types": [],
                "statuses": ["active", "failed", "partial", "promoted"],
                "needs_evidence": True,
                "limit": self.limit,
            },
        }
        data = self._llm_json(
            prompt,
            fallback={
                "query": query,
                "keywords": list(_tokens(query))[:8],
                "node_types": [],
                "statuses": ["active", "failed", "partial", "promoted"],
                "needs_evidence": True,
                "limit": self.limit,
            },
        )
        return RetrievalIntent(
            query=str(data.get("query") or query),
            keywords=[str(item) for item in data.get("keywords") or []],
            node_types=[str(item) for item in data.get("node_types") or data.get("memory_types") or []],
            statuses=[str(item) for item in data.get("statuses") or []],
            needs_evidence=bool(data.get("needs_evidence", True)),
            limit=int(data.get("limit") or self.limit),
        )

    def _evidence_snippets(self, intent: RetrievalIntent, tree_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not intent.needs_evidence:
            return []
        evidence_ids: list[str] = []
        for item in tree_results:
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            evidence_ids.extend(str(eid) for eid in meta.get("evidence_ids") or [])
        snippets = self.gateway.evidence_snippets(evidence_ids[: self.limit], query=intent.query)
        if not snippets or self.client is None:
            return snippets
        prompt = {
            "task": "Compress evidence snippets for model context without losing verifiable details.",
            "query": intent.query,
            "snippets": snippets,
            "output_json": {"snippets": [{"uri": "tree://...", "snippet": "short evidence"}]},
        }
        data = self._llm_json(prompt, fallback={"snippets": snippets})
        compact = data.get("snippets")
        return compact if isinstance(compact, list) else snippets

    def _promote_stable_tree_memory(self) -> None:
        tree_memory = self.gateway.tree_memory
        memory_store = self.gateway.memory_store
        if not hasattr(tree_memory, "promotion_candidates") or not hasattr(memory_store, "promote_tree_memory"):
            return
        for item in tree_memory.promotion_candidates(self.gateway.tree_id):
            uri = memory_store.promote_tree_memory(item)
            if uri and hasattr(tree_memory, "mark_promoted"):
                tree_memory.mark_promoted(self.gateway.tree_id, item.id)

    def _llm_json(self, payload: dict[str, Any], *, fallback: dict[str, Any]) -> dict[str, Any]:
        if self.client is None:
            return fallback
        if hasattr(self.client, "resps") or hasattr(self.client, "responses"):
            return fallback
        try:
            response = self.client.create_message(
                model=self.model,
                max_tokens=900,
                system="You are PrismX TGM 3.0 memory planner. Return only valid JSON.",
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                tools=[],
            )
            text = "\n".join(getattr(block, "text", "") for block in getattr(response, "content", []) if getattr(block, "text", ""))
            return _parse_json(text) or fallback
        except Exception:
            return fallback


def _long_term_category(category: str, memory_type: str | None) -> str:
    if memory_type in LONG_TERM_SPECIAL_MEMORY_TYPES:
        return LONG_TERM_SPECIAL_CATEGORY_MAP[str(memory_type)]
    if category in LONG_TERM_SPECIAL_MEMORY_TYPES:
        return LONG_TERM_SPECIAL_CATEGORY_MAP[category]
    return ""


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


def _tree_object_id_from_uri(uri: str) -> str:
    return uri.rstrip("/").rsplit("/", 1)[-1] if uri else ""


def _long_term_types_for_intent(intent: RetrievalIntent) -> list[str]:
    types = set()
    for node_type in intent.node_types:
        if node_type in {"decision", "conclusion", "hypothesis", "failure", "partial_fix"}:
            types.add("pattern")
        if node_type in {"constraint", "todo", "finding", "fact"}:
            types.add("project")
    return sorted(types)


def _parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()
    if "{" in text and "}" in text:
        text = text[text.index("{") : text.rindex("}") + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _tokens(text: str) -> set[str]:
    import re

    raw = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    tokens = set(raw)
    for token in raw:
        if len(token) > 3 and any("\u4e00" <= ch <= "\u9fff" for ch in token):
            tokens.update(token[i : i + 2] for i in range(len(token) - 1))
    return tokens
