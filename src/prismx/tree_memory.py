from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


TREE_MEMORY_TYPES = {
    "conclusion",
    "decision",
    "constraint",
    "todo",
    "finding",
    "hypothesis",
    "discarded_option",
    "fact",
}

TREE_MEMORY_STATUSES = {"active", "archived", "promoted", "discarded"}


@dataclass
class TreeMemoryItem:
    id: str
    tree_id: str
    title: str
    content: str
    memory_type: str = "finding"
    tags: list[str] = field(default_factory=list)
    source_session_id: str = ""
    source_branch: str = ""
    source_entry_id: str = ""
    confidence: float = 0.6
    reuse_count: int = 0
    status: str = "active"
    promoted: bool = False
    created_at: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def uri(self) -> str:
        return f"tree://{self.tree_id}/memory/{self.id}"


class TreeMemoryStore:
    """Project-level memory scoped to one TreeSession.

    Tree Memory is intentionally not raw chat history. It stores reusable
    findings, decisions, constraints, shared todos, hypotheses, and discarded
    options that sibling branches may safely recall.
    """

    def __init__(self, root: Path, *, legacy_root: Path | None = None) -> None:
        root = Path(root)
        if root.name == "tree" and root.parent.name == "memory":
            legacy_root = legacy_root or root
            root = root.parent.parent / "data" / "tree_memory"
        self.root = root
        self.legacy_root = Path(legacy_root) if legacy_root is not None else _legacy_root_for(root)
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
        if memory_type not in TREE_MEMORY_TYPES:
            memory_type = "finding"
        duplicate = self._find_duplicate(tree_id, content)
        now = _now()
        if duplicate is not None:
            item = duplicate
            item.title = (title or item.title or _title_from_content(content)).strip()
            item.content = content
            item.memory_type = memory_type
            item.tags = sorted(set(item.tags + list(tags or [])))
            item.source_session_id = source_session_id or item.source_session_id
            item.source_branch = source_branch or item.source_branch
            item.source_entry_id = source_entry_id or item.source_entry_id
            item.confidence = max(float(confidence), item.confidence)
            item.status = "active" if item.status == "discarded" else item.status
            item.updated_at = now
            item.metadata = {**item.metadata, **dict(metadata or {})}
        else:
            item = TreeMemoryItem(
                id=uuid4().hex[:10],
                tree_id=tree_id,
                title=(title or _title_from_content(content)).strip(),
                content=content,
                memory_type=memory_type,
                tags=list(tags or []),
                source_session_id=source_session_id,
                source_branch=source_branch,
                source_entry_id=source_entry_id,
                confidence=float(confidence),
                created_at=now,
                updated_at=now,
                metadata=dict(metadata or {}),
            )
        self._append(tree_id, {"op": "upsert", "item": asdict(item)})
        return item.uri

    def search(self, tree_id: str, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        tokens = _tokens(query)
        scored: list[tuple[float, TreeMemoryItem]] = []
        for item in self.items(tree_id):
            if item.status != "active":
                continue
            haystacks = {
                "title": item.title.lower(),
                "tags": " ".join(item.tags).lower(),
                "content": item.content.lower(),
                "type": item.memory_type.lower(),
            }
            score = 0.0
            for token in tokens:
                if token in haystacks["title"]:
                    score += 5
                if token in haystacks["tags"]:
                    score += 4
                if token in haystacks["type"]:
                    score += 3
                if token in haystacks["content"]:
                    score += 2
            if score > 0:
                score += item.confidence + min(item.reuse_count, 5) * 0.2
                scored.append((score, item))
        scored.sort(key=lambda pair: -pair[0])
        selected = [item for _, item in scored[:limit]]
        for item in selected:
            self.mark_reused(tree_id, item.id)
        return [self._to_context_result(item) for item in selected]

    def read(self, uri: str, layer: str = "auto") -> str:
        item = self._item_by_uri(uri)
        if item is None:
            return f"Error: URI not found: {uri}"
        if layer in {"l0", "metadata"}:
            return f"{item.title} [{item.memory_type}] confidence={item.confidence:.2f}"
        if layer in {"auto", "l1", "overview"}:
            return item.content
        return _render_full(item)

    def list(self, tree_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return [self._to_context_result(item) for item in self.items(tree_id)[:limit]]

    def items(self, tree_id: str) -> list[TreeMemoryItem]:
        state: dict[str, TreeMemoryItem] = {}
        paths = [self._legacy_path(tree_id), self._path(tree_id)]
        if not any(path.exists() for path in paths):
            return []
        for path in paths:
            if not path.exists():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                item_data = event.get("item") or {}
                item_id = item_data.get("id")
                if not item_id:
                    continue
                if event.get("op") == "delete":
                    state.pop(item_id, None)
                    continue
                item_data.setdefault("promoted", item_data.get("status") == "promoted")
                if item_data.get("status") not in TREE_MEMORY_STATUSES:
                    item_data["status"] = "active"
                state[item_id] = TreeMemoryItem(**item_data)
        return sorted(state.values(), key=lambda item: item.updated_at, reverse=True)

    def promotion_candidates(self, tree_id: str) -> list[TreeMemoryItem]:
        candidates = []
        for item in self.items(tree_id):
            if item.status != "active":
                continue
            if item.confidence >= 0.85 or item.reuse_count >= 3:
                candidates.append(item)
        return candidates

    def mark_reused(self, tree_id: str, item_id: str) -> None:
        item = next((entry for entry in self.items(tree_id) if entry.id == item_id), None)
        if item is None:
            return
        item.reuse_count += 1
        item.updated_at = _now()
        self._append(tree_id, {"op": "upsert", "item": asdict(item)})

    def delete(self, tree_id: str, item_id: str) -> bool:
        item = next((entry for entry in self.items(tree_id) if entry.id == item_id), None)
        if item is None:
            return False
        self._append(tree_id, {"op": "delete", "item": asdict(item)})
        return True

    def mark_promoted(self, tree_id: str, item_id: str) -> bool:
        item = next((entry for entry in self.items(tree_id) if entry.id == item_id), None)
        if item is None:
            return False
        item.status = "promoted"
        item.promoted = True
        item.updated_at = _now()
        self._append(tree_id, {"op": "upsert", "item": asdict(item)})
        return True

    def delete_tree(self, tree_id: str) -> None:
        self._path(tree_id).unlink(missing_ok=True)

    def _to_context_result(self, item: TreeMemoryItem) -> dict[str, Any]:
        return {
            "uri": item.uri,
            "context_type": "tree_memory",
            "title": item.title,
            "abstract": item.content[:200],
            "overview": item.content,
            "trust_score": item.confidence,
            "status": item.status,
            "promoted": item.promoted,
            "sensitivity": "public",
            "updated_at": item.updated_at,
            "tags": item.tags + [item.memory_type],
            "metadata": {
                "tree_id": item.tree_id,
                "source_session_id": item.source_session_id,
                "source_branch": item.source_branch,
                "source_entry_id": item.source_entry_id,
                "memory_type": item.memory_type,
                "reuse_count": item.reuse_count,
                "confidence": item.confidence,
                "status": item.status,
                "promoted": item.promoted,
                "scope": "tree",
            },
        }

    def _item_by_uri(self, uri: str) -> TreeMemoryItem | None:
        match = re.match(r"^tree://([^/]+)/memory/([^/]+)$", uri)
        if not match:
            return None
        tree_id, item_id = match.groups()
        return next((item for item in self.items(tree_id) if item.id == item_id), None)

    def _append(self, tree_id: str, event: dict[str, Any]) -> None:
        path = self._path(tree_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        event.setdefault("ts", _now())
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _path(self, tree_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", tree_id)
        return self.root / f"{safe}.jsonl"

    def _legacy_path(self, tree_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", tree_id)
        return self.legacy_root / f"{safe}.jsonl"

    def _find_duplicate(self, tree_id: str, content: str) -> TreeMemoryItem | None:
        normalized = _normalize_content(content)
        return next(
            (
                item
                for item in self.items(tree_id)
                if item.status in {"active", "archived"} and _normalize_content(item.content) == normalized
            ),
            None,
        )


def _render_full(item: TreeMemoryItem) -> str:
    return "\n".join(
        [
            f"# {item.title}",
            "",
            f"- URI: {item.uri}",
            f"- Type: {item.memory_type}",
            f"- Confidence: {item.confidence:.2f}",
            f"- Reuse count: {item.reuse_count}",
            f"- Source branch: {item.source_branch or '(unknown)'}",
            f"- Tags: {', '.join(item.tags) or '(none)'}",
            "",
            item.content,
        ]
    )


def _title_from_content(content: str) -> str:
    first = content.splitlines()[0].strip()
    return first[:60] + ("..." if len(first) > 60 else "")


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[\w一-鿿]+", text.lower())
    tokens = set(raw)
    for token in raw:
        if len(token) > 3 and any("\u4e00" <= ch <= "\u9fff" for ch in token):
            tokens.update(token[i : i + 2] for i in range(len(token) - 1))
    return tokens


def _normalize_content(content: str) -> str:
    return re.sub(r"\s+", " ", content.strip().lower())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _legacy_root_for(root: Path) -> Path | None:
    path = Path(root)
    if path.name == "tree" and path.parent.name == "memory":
        return path
    return path.parent.parent / "memory" / "tree" if path.name == "tree_memory" else path
