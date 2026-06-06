from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


TRACE_EVENT_TYPES = {
    "user",
    "assistant",
    "tool_call",
    "tool_result",
    "error",
    "test",
    "diff",
    "search",
    "note",
}

EVIDENCE_TYPES = {
    "command_output",
    "error_log",
    "file_diff",
    "search_result",
    "code_snippet",
    "test_result",
    "note",
}

FOLDED_NODE_TYPES = {
    "decision",
    "constraint",
    "finding",
    "conclusion",
    "todo",
    "hypothesis",
    "discarded_option",
    "fact",
    "failure",
    "partial_fix",
}

TREE_MEMORY_TYPES = FOLDED_NODE_TYPES
TREE_MEMORY_STATUSES = {"active", "archived", "promoted", "discarded", "failed", "partial"}

EVIDENCE_DIR_BY_TYPE = {
    "command_output": "command_outputs",
    "error_log": "error_logs",
    "file_diff": "file_diffs",
    "search_result": "search_results",
    "code_snippet": "code_snippets",
    "test_result": "test_results",
    "note": "code_snippets",
}


@dataclass
class TraceEvent:
    id: str
    tree_id: str
    session_id: str
    event_type: str
    content: str
    created_at: str
    actor: str = "agent"
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def uri(self) -> str:
        return f"tree://{self.tree_id}/trace/{self.id}"


@dataclass
class Evidence:
    id: str
    tree_id: str
    evidence_type: str
    title: str
    path: str
    created_at: str
    source_event_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def uri(self) -> str:
        return f"tree://{self.tree_id}/evidence/{self.id}"


@dataclass
class FoldedNode:
    id: str
    tree_id: str
    title: str
    summary: str
    node_type: str = "finding"
    status: str = "active"
    confidence: float = 0.6
    reuse_count: int = 0
    promoted: bool = False
    source_event_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def uri(self) -> str:
        return f"tree://{self.tree_id}/fold/{self.id}"

    # Compatibility with the old TGM 2.0 TreeMemoryItem shape.
    @property
    def content(self) -> str:
        return self.summary

    @property
    def memory_type(self) -> str:
        return self.node_type

    @property
    def source_session_id(self) -> str:
        return str(self.metadata.get("source_session_id") or "")


TreeMemoryItem = FoldedNode


@dataclass
class MemoryIndexItem:
    id: str
    tree_id: str
    fold_id: str
    title: str
    description: str
    tags: list[str] = field(default_factory=list)
    node_type: str = "finding"
    status: str = "active"
    confidence: float = 0.6
    updated_at: str = ""


@dataclass
class RetrievalIntent:
    query: str
    keywords: list[str] = field(default_factory=list)
    node_types: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    needs_evidence: bool = True
    limit: int = 5


@dataclass
class ContextPacket:
    query: str
    active_path_summary: str = ""
    coarse_reasoning: str = ""
    retrieval_intent: RetrievalIntent | None = None
    tree_memory: list[dict[str, Any]] = field(default_factory=list)
    evidence_snippets: list[dict[str, Any]] = field(default_factory=list)
    long_term: list[dict[str, Any]] = field(default_factory=list)

    def render(self, *, max_chars: int = 12000) -> str:
        lines = ["## Runtime Recall"]
        if self.active_path_summary:
            lines.extend(["", "### Active Path Context", self.active_path_summary[:1600]])
        if self.coarse_reasoning:
            lines.extend(["", "### Coarse Reasoning", self.coarse_reasoning[:1200]])
        if self.retrieval_intent:
            lines.extend(["", "### Retrieval Intent", self.retrieval_intent.query])
        if self.tree_memory:
            lines.extend(["", "### Tree Memory"])
            for item in self.tree_memory:
                lines.append(_render_context_item(item))
        if self.evidence_snippets:
            lines.extend(["", "### Evidence Snippets"])
            for item in self.evidence_snippets:
                lines.append(f"- {item.get('uri', '')}: {item.get('snippet', '')}")
        if self.long_term:
            lines.extend(["", "### Long-term Knowledge"])
            for item in self.long_term:
                lines.append(_render_context_item(item))
        if len(lines) == 1:
            return "(No runtime context recalled.)"
        rendered = "\n".join(lines)
        if len(rendered) <= max_chars:
            return rendered
        return rendered[: max_chars - 80].rstrip() + "\n...[runtime recall truncated]"


class TreeMemoryStore:
    """Tree Memory 3.0 execution memory store.

    New data is directory based:
    data/tree_memory/{tree_id}/trace_events.jsonl, folded_nodes.jsonl,
    memory_index.jsonl, tree_state.json, and evidence/*.
    """

    def __init__(self, root: Path, *, legacy_root: Path | None = None) -> None:
        root = Path(root)
        if root.name == "tree" and root.parent.name == "memory":
            root = root.parent.parent / "data" / "tree_memory"
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def remember(
        self,
        tree_id: str,
        content: str,
        *,
        title: str | None = None,
        memory_type: str = "finding",
        tags: list[str] | None = None,
        source_session_id: str = "",
        source_branch: str = "",
        source_entry_id: str = "",
        confidence: float = 0.6,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        content = content.strip()
        if not content:
            return ""
        event = self.record_event(
            tree_id,
            "note",
            content,
            session_id=source_session_id,
            actor="user",
            metadata={
                "source_branch": source_branch,
                "source_entry_id": source_entry_id,
                **dict(metadata or {}),
            },
        )
        evidence = self.store_evidence(
            tree_id,
            "note",
            content,
            title=title or _title_from_content(content),
            source_event_id=event.id,
        )
        fold = self.fold(
            tree_id,
            title=title or _title_from_content(content),
            summary=content,
            node_type=memory_type if memory_type in FOLDED_NODE_TYPES else "finding",
            tags=tags or [],
            evidence_ids=[evidence.id],
            source_event_ids=[event.id],
            confidence=confidence,
            metadata={
                "source_session_id": source_session_id,
                "source_branch": source_branch,
                "source_entry_id": source_entry_id,
                **dict(metadata or {}),
            },
        )
        return fold.uri

    def record_event(
        self,
        tree_id: str,
        event_type: str,
        content: str,
        *,
        session_id: str = "",
        actor: str = "agent",
        evidence_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceEvent:
        now = _now()
        event = TraceEvent(
            id=uuid4().hex[:12],
            tree_id=str(tree_id),
            session_id=session_id,
            event_type=event_type if event_type in TRACE_EVENT_TYPES else "note",
            content=content,
            actor=actor,
            evidence_ids=list(evidence_ids or []),
            metadata=dict(metadata or {}),
            created_at=now,
        )
        self._append_jsonl(self._trace_path(tree_id), asdict(event))
        self._write_state(tree_id)
        return event

    def store_evidence(
        self,
        tree_id: str,
        evidence_type: str,
        content: str,
        *,
        title: str | None = None,
        source_event_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Evidence:
        evidence_type = evidence_type if evidence_type in EVIDENCE_TYPES else "note"
        evidence_id = uuid4().hex[:12]
        now = _now()
        rel = Path("evidence") / EVIDENCE_DIR_BY_TYPE[evidence_type] / f"{evidence_id}.txt"
        path = self._tree_dir(tree_id) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        evidence = Evidence(
            id=evidence_id,
            tree_id=str(tree_id),
            evidence_type=evidence_type,
            title=title or _title_from_content(content),
            path=str(rel).replace("\\", "/"),
            source_event_id=source_event_id,
            metadata=dict(metadata or {}),
            created_at=now,
        )
        self._append_jsonl(self._evidence_index_path(tree_id), asdict(evidence))
        return evidence

    def fold(
        self,
        tree_id: str,
        *,
        title: str,
        summary: str,
        node_type: str = "finding",
        status: str = "active",
        tags: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        source_event_ids: list[str] | None = None,
        confidence: float = 0.6,
        metadata: dict[str, Any] | None = None,
    ) -> FoldedNode:
        duplicate = self._find_duplicate_fold(tree_id, summary)
        now = _now()
        if duplicate is not None:
            fold = duplicate
            fold.title = title or fold.title
            fold.summary = summary
            fold.node_type = node_type if node_type in FOLDED_NODE_TYPES else fold.node_type
            fold.status = status if status in TREE_MEMORY_STATUSES else fold.status
            fold.tags = sorted(set(fold.tags + list(tags or [])))
            fold.evidence_ids = sorted(set(fold.evidence_ids + list(evidence_ids or [])))
            fold.source_event_ids = sorted(set(fold.source_event_ids + list(source_event_ids or [])))
            fold.confidence = max(float(confidence), fold.confidence)
            fold.updated_at = now
            fold.metadata = {**fold.metadata, **dict(metadata or {})}
        else:
            fold = FoldedNode(
                id=uuid4().hex[:12],
                tree_id=str(tree_id),
                title=title.strip() or _title_from_content(summary),
                summary=summary.strip(),
                node_type=node_type if node_type in FOLDED_NODE_TYPES else "finding",
                status=status if status in TREE_MEMORY_STATUSES else "active",
                tags=list(tags or []),
                evidence_ids=list(evidence_ids or []),
                source_event_ids=list(source_event_ids or []),
                confidence=float(confidence),
                created_at=now,
                updated_at=now,
                metadata=dict(metadata or {}),
            )
        self._append_jsonl(self._folds_path(tree_id), {"op": "upsert", "fold": asdict(fold)})
        self._upsert_index(fold)
        return fold

    def fold_trace_events(self, tree_id: str, *, limit: int = 20, title: str | None = None) -> FoldedNode | None:
        events = self.trace_events(tree_id)[-limit:]
        if not events:
            return None
        summary = "\n".join(f"{event.event_type}: {event.content}" for event in events)
        evidence = self.store_evidence(
            tree_id,
            "note",
            summary,
            title=title or "Trace fold evidence",
            source_event_id=events[-1].id,
        )
        return self.fold(
            tree_id,
            title=title or _title_from_content(summary),
            summary=summary,
            node_type="finding",
            evidence_ids=[evidence.id],
            source_event_ids=[event.id for event in events],
            confidence=0.65,
        )

    def retrieve(self, tree_id: str, intent: RetrievalIntent | dict[str, Any] | str, *, limit: int = 5) -> list[dict[str, Any]]:
        if isinstance(intent, str):
            intent_obj = RetrievalIntent(query=intent, limit=limit)
        elif isinstance(intent, dict):
            intent_obj = RetrievalIntent(
                query=str(intent.get("query") or ""),
                keywords=[str(item) for item in intent.get("keywords") or []],
                node_types=[str(item) for item in intent.get("node_types") or intent.get("memory_types") or []],
                statuses=[str(item) for item in intent.get("statuses") or []],
                needs_evidence=bool(intent.get("needs_evidence", True)),
                limit=int(intent.get("limit") or limit),
            )
        else:
            intent_obj = intent
        scored: list[tuple[float, FoldedNode]] = []
        tokens = _tokens(" ".join([intent_obj.query, *intent_obj.keywords]))
        for fold in self.items(tree_id):
            if intent_obj.statuses and fold.status not in intent_obj.statuses:
                continue
            if not intent_obj.statuses and fold.status in {"archived", "discarded"}:
                continue
            if intent_obj.node_types and fold.node_type not in intent_obj.node_types:
                continue
            haystack = " ".join([fold.title, fold.summary, fold.node_type, " ".join(fold.tags)]).lower()
            score = sum(3 if token in fold.title.lower() else 1 for token in tokens if token in haystack)
            if score <= 0 and tokens:
                continue
            score += fold.confidence + min(fold.reuse_count, 8) * 0.15
            scored.append((score, fold))
        scored.sort(key=lambda pair: (-pair[0], pair[1].updated_at))
        selected = [fold for _, fold in scored[: intent_obj.limit or limit]]
        for fold in selected:
            self.mark_reused(tree_id, fold.id)
        return [self._to_context_result(fold) for fold in selected]

    def search(self, tree_id: str, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        return self.retrieve(tree_id, RetrievalIntent(query=query, limit=limit), limit=limit)

    def snippet(self, tree_id: str, evidence_ids: list[str], *, query: str = "", limit_chars: int = 1800) -> list[dict[str, Any]]:
        snippets = []
        for evidence_id in evidence_ids:
            evidence = self.evidence(tree_id, evidence_id)
            if evidence is None:
                continue
            text = self.read_evidence(evidence)
            snippet = _best_snippet(text, query, limit_chars)
            snippets.append({"uri": evidence.uri, "title": evidence.title, "snippet": snippet, "evidence_id": evidence.id})
        return snippets

    def rollback_plan(self, tree_id: str, fold_id: str) -> dict[str, Any]:
        fold = self.fold_by_id(tree_id, fold_id)
        if fold is None:
            raise KeyError(f"fold not found: {fold_id}")
        files = sorted(
            {
                str(value)
                for evidence_id in fold.evidence_ids
                for value in [self.evidence(tree_id, evidence_id)]
                if value is not None
                for value in [value.metadata.get("file") or value.metadata.get("path")]
                if value
            }
        )
        return {
            "foldId": fold.id,
            "title": fold.title,
            "related_files": files,
            "evidence_refs": [f"tree://{tree_id}/evidence/{eid}" for eid in fold.evidence_ids],
            "suggested_steps": [
                "Read the referenced evidence before editing.",
                "Revert or adjust only the files tied to this fold.",
                "Run the narrowest available verification after the change.",
            ],
            "risk": "Review carefully: rollback plans are advisory and evidence-based.",
        }

    def archive(self, tree_id: str, fold_id: str, *, status: str = "archived") -> bool:
        fold = self.fold_by_id(tree_id, fold_id)
        if fold is None:
            return False
        fold.status = status if status in TREE_MEMORY_STATUSES else "archived"
        fold.updated_at = _now()
        self._append_jsonl(self._folds_path(tree_id), {"op": "upsert", "fold": asdict(fold)})
        self._upsert_index(fold)
        return True

    def mark_promoted(self, tree_id: str, item_id: str) -> bool:
        fold = self.fold_by_id(tree_id, item_id)
        if fold is None:
            return False
        fold.status = "promoted"
        fold.promoted = True
        fold.updated_at = _now()
        self._append_jsonl(self._folds_path(tree_id), {"op": "upsert", "fold": asdict(fold)})
        self._upsert_index(fold)
        return True

    def mark_reused(self, tree_id: str, item_id: str) -> None:
        fold = self.fold_by_id(tree_id, item_id)
        if fold is None:
            return
        fold.reuse_count += 1
        fold.updated_at = _now()
        self._append_jsonl(self._folds_path(tree_id), {"op": "upsert", "fold": asdict(fold)})
        self._upsert_index(fold)

    def delete(self, tree_id: str, item_id: str) -> bool:
        fold = self.fold_by_id(tree_id, item_id)
        if fold is None:
            return False
        self._append_jsonl(self._folds_path(tree_id), {"op": "delete", "fold": asdict(fold)})
        self._append_jsonl(self._index_path(tree_id), {"op": "delete", "index": {"fold_id": item_id, "id": item_id}})
        return True

    def list(self, tree_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return [self._to_context_result(fold) for fold in self.items(tree_id)[:limit]]

    def items(self, tree_id: str) -> list[FoldedNode]:
        state: dict[str, FoldedNode] = {}
        paths = [self._folds_path(tree_id)]
        legacy_path = self.root / (tree_id + ".jsonl")
        if legacy_path.exists():
            paths.append(legacy_path)
        for path in paths:
            if not path.exists():
                continue
            for row in _read_jsonl(path):
                fold_data = row.get("fold") or row.get("item") or row
                fold_id = fold_data.get("id")
                if not fold_id:
                    continue
                if row.get("op") == "delete":
                    state.pop(fold_id, None)
                    continue
                fold_data.setdefault("node_type", fold_data.get("memory_type", "finding"))
                fold_data.setdefault("summary", fold_data.get("content", ""))
                fold_data.setdefault("promoted", fold_data.get("status") == "promoted")
                fold_data.setdefault("source_event_ids", [])
                fold_data.setdefault("evidence_ids", [])
                fold_data.setdefault("metadata", {})
                state[fold_id] = FoldedNode(**{key: value for key, value in fold_data.items() if key in FoldedNode.__dataclass_fields__})
        return sorted(state.values(), key=lambda item: item.updated_at, reverse=True)

    def trace_events(self, tree_id: str, *, limit: int | None = None) -> list[TraceEvent]:
        events = []
        for row in _read_jsonl(self._trace_path(tree_id)):
            try:
                events.append(TraceEvent(**row))
            except TypeError:
                continue
        return events[-limit:] if limit else events

    def evidence(self, tree_id: str, evidence_id: str) -> Evidence | None:
        for row in _read_jsonl(self._evidence_index_path(tree_id)):
            if row.get("id") != evidence_id:
                continue
            try:
                return Evidence(**row)
            except TypeError:
                return None
        return None

    def read_evidence(self, evidence: Evidence) -> str:
        path = self._tree_dir(evidence.tree_id) / evidence.path
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def fold_by_id(self, tree_id: str, fold_id: str) -> FoldedNode | None:
        return next((fold for fold in self.items(tree_id) if fold.id == fold_id), None)

    def read(self, uri: str, layer: str = "auto") -> str:
        tree_id, kind, object_id = _parse_tree_uri(uri)
        if not tree_id:
            return f"Error: URI not found: {uri}"
        if kind == "evidence":
            evidence = self.evidence(tree_id, object_id)
            return self.read_evidence(evidence) if evidence else f"Error: URI not found: {uri}"
        fold = self.fold_by_id(tree_id, object_id)
        if fold is None:
            return f"Error: URI not found: {uri}"
        if layer in {"l0", "metadata"}:
            return f"{fold.title} [{fold.node_type}] confidence={fold.confidence:.2f}"
        if layer in {"auto", "l1", "overview"}:
            return fold.summary
        return _render_full(fold)

    def promotion_candidates(self, tree_id: str) -> list[FoldedNode]:
        return [
            fold
            for fold in self.items(tree_id)
            if fold.status == "active" and not fold.promoted and (fold.confidence >= 0.85 or fold.reuse_count >= 3)
        ]

    def status(self, tree_id: str) -> dict[str, Any]:
        tree_dir = self._tree_dir(tree_id)
        folds = self.items(tree_id)
        evidence_items = list(_read_jsonl(self._evidence_index_path(tree_id)))
        return {
            "treeId": tree_id,
            "path": str(tree_dir),
            "traceEvents": len(self.trace_events(tree_id)),
            "foldedNodes": len(folds),
            "evidence": len(evidence_items),
            "evidence_items": [{"id": ev.get("id", ""), "evidenceType": ev.get("evidence_type", "note"), "title": ev.get("title", ev.get("id", "")), "sourceEventId": ev.get("source_event_id", ""), "createdAt": ev.get("created_at", "")} for ev in evidence_items],
            "active": sum(1 for fold in folds if fold.status == "active"),
            "promoted": sum(1 for fold in folds if fold.promoted or fold.status == "promoted"),
        }

    def delete_tree(self, tree_id: str) -> None:
        # Keep this non-recursive for safety; Workspace deletion can leave runtime traces.
        state = self._tree_dir(tree_id) / "tree_state.json"
        state.unlink(missing_ok=True)

    def _to_context_result(self, fold: FoldedNode) -> dict[str, Any]:
        return {
            "uri": fold.uri,
            "context_type": "tree_memory",
            "title": fold.title,
            "abstract": fold.summary[:240],
            "overview": fold.summary,
            "trust_score": fold.confidence,
            "status": fold.status,
            "promoted": fold.promoted,
            "sensitivity": "public",
            "updated_at": fold.updated_at,
            "tags": fold.tags + [fold.node_type],
            "metadata": {
                "tree_id": fold.tree_id,
                "fold_id": fold.id,
                "node_type": fold.node_type,
                "memory_type": fold.node_type,
                "reuse_count": fold.reuse_count,
                "confidence": fold.confidence,
                "status": fold.status,
                "promoted": fold.promoted,
                "evidence_ids": fold.evidence_ids,
                "source_event_ids": fold.source_event_ids,
                "source_session_id": fold.source_session_id,
                "scope": "tree",
            },
        }

    def _upsert_index(self, fold: FoldedNode) -> None:
        index = MemoryIndexItem(
            id=fold.id,
            tree_id=fold.tree_id,
            fold_id=fold.id,
            title=fold.title,
            description=fold.summary[:240],
            tags=fold.tags,
            node_type=fold.node_type,
            status=fold.status,
            confidence=fold.confidence,
            updated_at=fold.updated_at,
        )
        self._append_jsonl(self._index_path(fold.tree_id), {"op": "upsert", "index": asdict(index)})

    def _find_duplicate_fold(self, tree_id: str, summary: str) -> FoldedNode | None:
        normalized = _normalize_content(summary)
        return next((fold for fold in self.items(tree_id) if _normalize_content(fold.summary) == normalized), None)

    def _tree_dir(self, tree_id: str) -> Path:
        path = self.root / _safe_id(tree_id)
        path.mkdir(parents=True, exist_ok=True)
        for child in EVIDENCE_DIR_BY_TYPE.values():
            (path / "evidence" / child).mkdir(parents=True, exist_ok=True)
        return path

    def _trace_path(self, tree_id: str) -> Path:
        return self._tree_dir(tree_id) / "trace_events.jsonl"

    def _folds_path(self, tree_id: str) -> Path:
        return self._tree_dir(tree_id) / "folded_nodes.jsonl"

    def _index_path(self, tree_id: str) -> Path:
        return self._tree_dir(tree_id) / "memory_index.jsonl"

    def _evidence_index_path(self, tree_id: str) -> Path:
        return self._tree_dir(tree_id) / "evidence_index.jsonl"

    def _write_state(self, tree_id: str) -> None:
        path = self._tree_dir(tree_id) / "tree_state.json"
        payload = {"tree_id": tree_id, "updated_at": _now(), "schema": "tgm-3.0"}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _render_context_item(item: dict[str, Any]) -> str:
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return (
        f"- URI: {item.get('uri', '')}\n"
        f"  Type: {meta.get('node_type') or meta.get('type') or item.get('context_type', '')}\n"
        f"  Trust: {item.get('trust_score', '?')}\n"
        f"  Summary: {item.get('abstract') or item.get('overview') or ''}"
    )


def _render_full(fold: FoldedNode) -> str:
    return "\n".join(
        [
            f"# {fold.title}",
            "",
            f"- URI: {fold.uri}",
            f"- Type: {fold.node_type}",
            f"- Confidence: {fold.confidence:.2f}",
            f"- Reuse count: {fold.reuse_count}",
            f"- Status: {fold.status}",
            f"- Evidence: {', '.join(fold.evidence_ids) or '(none)'}",
            f"- Tags: {', '.join(fold.tags) or '(none)'}",
            "",
            fold.summary,
        ]
    )


def _read_jsonl(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _parse_tree_uri(uri: str) -> tuple[str, str, str]:
    match = re.match(r"^tree://([^/]+)/(fold|memory|evidence|trace)/([^/]+)$", uri)
    if not match:
        return "", "", ""
    tree_id, kind, object_id = match.groups()
    if kind == "memory":
        kind = "fold"
    return tree_id, kind, object_id


def _title_from_content(content: str) -> str:
    first = content.splitlines()[0].strip()
    return first[:60] + ("..." if len(first) > 60 else "")


def _best_snippet(text: str, query: str, limit_chars: int) -> str:
    text = text.strip()
    if len(text) <= limit_chars:
        return text
    tokens = _tokens(query)
    lower = text.lower()
    positions = [lower.find(token) for token in tokens if lower.find(token) >= 0]
    start = max(0, min(positions) - 200) if positions else 0
    return text[start : start + limit_chars].strip()


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    tokens = set(raw)
    for token in raw:
        if len(token) > 3 and any("\u4e00" <= ch <= "\u9fff" for ch in token):
            tokens.update(token[i : i + 2] for i in range(len(token) - 1))
    return tokens


def _normalize_content(content: str) -> str:
    return re.sub(r"\s+", " ", content.strip().lower())


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", str(value))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
