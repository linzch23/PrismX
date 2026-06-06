from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UTC8 = timezone(timedelta(hours=8))

LONG_TERM_MEMORY_TYPES = {"user", "feedback", "project", "reference", "pattern"}

CATEGORY_TO_LONG_TERM_TYPE = {
    "profile": "user",
    "preferences": "feedback",
    "entities": "user",
    "events": "project",
    "decisions": "project",
    "constraints": "project",
    "open_tasks": "project",
    "cases": "project",
    "patterns": "pattern",
    "tools": "reference",
    "skills": "reference",
    "research": "reference",
}


@dataclass
class KnowledgeNode:
    id: str
    name: str
    description: str
    type: str
    source_tree_id: str
    source_fold_id: str
    source_evidence_ids: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    confidence: float = 0.6
    status: str = "active"
    tags: list[str] = field(default_factory=list)
    content: str = ""

    @property
    def uri(self) -> str:
        return f"mem://{self.type}/{self.id}"

    @property
    def source_memory_id(self) -> str:
        return self.source_fold_id


@dataclass
class KnowledgeEdge:
    id: str
    source_uri: str
    target_uri: str
    relation: str
    confidence: float = 0.8
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


LongTermMemory = KnowledgeNode


class MemoryStore:
    """Long-term Knowledge 3.0 store.

    Long-term Knowledge is written only from traceable Tree Memory folds.
    New writes use data/knowledge/MEMORY.md, memories/*, graph/*, and
    promotion_log.jsonl.
    """

    def __init__(self, memory_dir: Path, user_file: Path | None = None) -> None:
        memory_dir = Path(memory_dir)
        if memory_dir.name == "memory":
            memory_dir = memory_dir.parent / "data" / "knowledge"
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.user_file = user_file or self.memory_dir / "USER.md"
        if not self.user_file.exists():
            self.user_file.parent.mkdir(parents=True, exist_ok=True)
            self.user_file.write_text("# User Profile\n\n", encoding="utf-8")

        self.memories_root = self.memory_dir / "memories"
        self.graph_root = self.memory_dir / "graph"
        for memory_type in LONG_TERM_MEMORY_TYPES:
            (self.memories_root / memory_type).mkdir(parents=True, exist_ok=True)
        self.graph_root.mkdir(parents=True, exist_ok=True)
        self.memory_index_path = self.memory_dir / "MEMORY.md"
        self.nodes_path = self.graph_root / "nodes.jsonl"
        self.edges_path = self.graph_root / "edges.jsonl"
        self.promotion_log_path = self.memory_dir / "promotion_log.jsonl"
        self.last_committed_knowledge_uris: list[str] = []
        self._auto_link_client = None
        self._auto_link_model = ""
        self._write_memory_index()

    def set_auto_link_client(self, client: Any, model: str) -> None:
        self._auto_link_client = client
        self._auto_link_model = model

    def read_user(self) -> str:
        return self.user_file.read_text(encoding="utf-8").strip()

    def write_user(self, content: str) -> None:
        self.user_file.write_text(content.strip() + "\n", encoding="utf-8")

    def today_episode_path(self) -> Path:
        return self.memory_dir / f"{datetime.now(UTC8).strftime('%Y-%m-%d')}.md"

    def read_today_episode(self) -> str:
        path = self.today_episode_path()
        return path.read_text(encoding="utf-8").strip() if path.exists() else ""

    def append_episode(self, content: str) -> None:
        content = content.strip()
        if not content:
            return
        path = self.today_episode_path()
        existing = path.read_text(encoding="utf-8") if path.exists() else f"# {path.stem} Episode Memory\n"
        path.write_text(existing.rstrip() + "\n\n" + content + "\n", encoding="utf-8")

    def remember_note(
        self,
        note: str,
        category: str = "events",
        title: str | None = None,
        *,
        source_tree_id: str = "",
        source_memory_id: str = "",
        source_fold_id: str = "",
        source_evidence_ids: list[str] | None = None,
        confidence: float = 0.8,
        tags: list[str] | None = None,
    ) -> str:
        fold_id = source_fold_id or source_memory_id
        if not note.strip() or not source_tree_id or not fold_id:
            return ""
        memory_type = CATEGORY_TO_LONG_TERM_TYPE.get(category, category if category in LONG_TERM_MEMORY_TYPES else "project")
        node = KnowledgeNode(
            id=_slugify(f"{source_tree_id}-{fold_id}"),
            name=title or _title_from_content(note),
            description=note.strip()[:240],
            type=memory_type,
            source_tree_id=source_tree_id,
            source_fold_id=fold_id,
            source_evidence_ids=list(source_evidence_ids or []),
            created_at=_now(),
            updated_at=_now(),
            confidence=float(confidence),
            status="active",
            tags=list(tags or [category]),
            content=note.strip(),
        )
        return self._write_knowledge(node, promotion_reason="direct-special")

    def promote_tree_memory(self, item: Any, *, memory_type: str | None = None) -> str:
        source_tree_id = str(getattr(item, "tree_id", ""))
        source_fold_id = str(getattr(item, "id", ""))
        if not source_tree_id or not source_fold_id:
            return ""
        target_type = memory_type or _long_term_type_for_fold(item)
        if target_type not in LONG_TERM_MEMORY_TYPES:
            target_type = "project"
        content = str(getattr(item, "summary", "") or getattr(item, "content", ""))
        node = KnowledgeNode(
            id=_slugify(f"{source_tree_id}-{source_fold_id}"),
            name=str(getattr(item, "title", "") or _title_from_content(content)),
            description=content[:240],
            type=target_type,
            source_tree_id=source_tree_id,
            source_fold_id=source_fold_id,
            source_evidence_ids=list(getattr(item, "evidence_ids", []) or []),
            created_at=_now(),
            updated_at=_now(),
            confidence=float(getattr(item, "confidence", 0.6)),
            status="active",
            tags=list(getattr(item, "tags", []) or []) + [str(getattr(item, "node_type", "finding"))],
            content=content,
        )
        return self._write_knowledge(node, promotion_reason="tree-memory-promotion")

    def commit_session_archive(
        self, session_uri: str, summary: str, operations: list[dict[str, Any]], metadata: dict[str, Any]
    ) -> str:
        self.last_committed_knowledge_uris = []
        for op in operations:
            if op.get("action") not in {"upsert", "append", "promote"}:
                continue
            source_tree_id = str(op.get("source_tree_id") or "")
            source_fold_id = str(op.get("source_fold_id") or op.get("source_memory_id") or "")
            memory_type = str(op.get("type") or op.get("long_term_type") or CATEGORY_TO_LONG_TERM_TYPE.get(str(op.get("category")), "project"))
            if memory_type not in LONG_TERM_MEMORY_TYPES or not source_tree_id or not source_fold_id:
                continue
            node = KnowledgeNode(
                id=_slugify(f"{source_tree_id}-{source_fold_id}"),
                name=str(op.get("title") or op.get("name") or op.get("key") or source_fold_id),
                description=str(op.get("abstract") or op.get("overview") or "")[:240],
                type=memory_type,
                source_tree_id=source_tree_id,
                source_fold_id=source_fold_id,
                source_evidence_ids=list(op.get("source_evidence_ids") or []),
                created_at=_now(),
                updated_at=_now(),
                confidence=float(op.get("trust_score") or op.get("confidence") or 0.6),
                status="active",
                tags=list(op.get("tags") or []),
                content=str(op.get("content") or op.get("overview") or summary or ""),
            )
            uri = self._write_knowledge(node, promotion_reason="session-archive")
            if uri:
                self.last_committed_knowledge_uris.append(uri)
        return session_uri

    def search_memory(self, query: str | dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
        if isinstance(query, dict):
            q = str(query.get("query") or "")
            keywords = [str(item) for item in query.get("keywords") or []]
            types = {str(item) for item in query.get("types") or query.get("memory_types") or []}
        else:
            q = str(query)
            keywords = []
            types = set()
        tokens = _tokens(" ".join([q, *keywords]))
        scored: list[tuple[float, KnowledgeNode]] = []
        for node in self._load_nodes_from_index():
            if node.status != "active":
                continue
            if types and node.type not in types:
                continue
            haystack = " ".join([node.name, node.description, node.type, " ".join(node.tags)]).lower()
            score = sum(4 if token in node.name.lower() else 1 for token in tokens if token in haystack)
            if score <= 0 and tokens:
                continue
            scored.append((score + node.confidence, node))
        scored.sort(key=lambda pair: (-pair[0], pair[1].updated_at))
        return [self._to_context_result(self._load_full_node(node) or node, include_content=True) for _, node in scored[:limit]]

    def read_context(self, uri: str, layer: str = "auto") -> str:
        node = self._node_by_uri(uri)
        if node is None:
            return f"Error: URI not found: {uri}"
        if layer in {"l0", "metadata"}:
            return node.description
        return node.content

    def list_context(self, prefix: str = "mem://", limit: int = 50) -> list[dict[str, Any]]:
        items = [self._to_context_result(node, include_content=True) for node in self._load_long_term_memories()]
        if prefix:
            items = [item for item in items if str(item.get("uri", "")).startswith(prefix)]
        return items[:limit]

    def graph_neighbors(self, uri: str, limit: int = 5) -> list[dict[str, Any]]:
        neighbors = []
        for row in _read_jsonl(self.edges_path):
            if row.get("source_uri") == uri or row.get("target_uri") == uri:
                neighbors.append(row)
        return neighbors[:limit]

    def render_memory(self) -> str:
        lines = ["# Long-term Memory"]
        for memory_type in ["user", "feedback", "project", "reference", "pattern"]:
            lines.append(f"\n## {memory_type}")
            bucket = [item for item in self._load_long_term_memories() if item.type == memory_type]
            if not bucket:
                lines.append("- (none)")
                continue
            for item in bucket:
                lines.append(f"- [{item.name}]({item.uri}) trust={item.confidence:.1f}")
        return "\n".join(lines)

    def _write_knowledge(self, node: KnowledgeNode, *, promotion_reason: str) -> str:
        if node.type not in LONG_TERM_MEMORY_TYPES or not node.source_tree_id or not node.source_fold_id:
            return ""
        path = self._memory_path(node.type, node.id)
        existing = self._read_knowledge(path)
        if existing is not None:
            node.created_at = existing.created_at
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_knowledge_markdown(node), encoding="utf-8")
        self._append_jsonl(self.nodes_path, {"op": "upsert", "node": _node_index_payload(node)})
        self._append_jsonl(
            self.edges_path,
            asdict(
                KnowledgeEdge(
                    id=_slugify(f"{node.source_tree_id}-{node.source_fold_id}-{node.id}"),
                    source_uri=f"tree://{node.source_tree_id}/fold/{node.source_fold_id}",
                    target_uri=node.uri,
                    relation="promoted_to",
                    confidence=node.confidence,
                    created_at=_now(),
                    metadata={"evidence_ids": node.source_evidence_ids},
                )
            ),
        )
        self._append_jsonl(
            self.promotion_log_path,
            {
                "ts": _now(),
                "reason": promotion_reason,
                "source_tree_id": node.source_tree_id,
                "source_fold_id": node.source_fold_id,
                "source_evidence_ids": node.source_evidence_ids,
                "target_uri": node.uri,
                "type": node.type,
            },
        )
        self._write_memory_index()
        return node.uri

    def _load_long_term_memories(self) -> list[KnowledgeNode]:
        nodes = []
        for memory_type in sorted(LONG_TERM_MEMORY_TYPES):
            for path in sorted((self.memories_root / memory_type).glob("*.md")):
                node = self._read_knowledge(path)
                if node is not None:
                    nodes.append(node)
        return sorted(nodes, key=lambda item: item.updated_at, reverse=True)

    def _load_nodes_from_index(self) -> list[KnowledgeNode]:
        state: dict[str, KnowledgeNode] = {}
        for row in _read_jsonl(self.nodes_path):
            node_data = row.get("node") or row
            if not node_data.get("id"):
                continue
            try:
                state[str(node_data["id"])] = KnowledgeNode(
                    id=str(node_data["id"]),
                    name=str(node_data.get("name") or node_data["id"]),
                    description=str(node_data.get("description") or ""),
                    type=str(node_data.get("type") or "project"),
                    source_tree_id=str(node_data.get("source_tree_id") or ""),
                    source_fold_id=str(node_data.get("source_fold_id") or node_data.get("source_memory_id") or ""),
                    source_evidence_ids=list(node_data.get("source_evidence_ids") or []),
                    created_at=str(node_data.get("created_at") or ""),
                    updated_at=str(node_data.get("updated_at") or ""),
                    confidence=float(node_data.get("confidence") or 0.6),
                    status=str(node_data.get("status") or "active"),
                    tags=list(node_data.get("tags") or []),
                    content="",
                )
            except (KeyError, TypeError, ValueError):
                continue
        if state:
            return sorted(state.values(), key=lambda item: item.updated_at, reverse=True)
        return [
            KnowledgeNode(**{**asdict(node), "content": ""})
            for node in self._load_long_term_memories()
        ]

    def _load_full_node(self, node: KnowledgeNode) -> KnowledgeNode | None:
        return self._read_knowledge(self._memory_path(node.type, node.id))

    def _read_knowledge(self, path: Path) -> KnowledgeNode | None:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        frontmatter, content = _split_frontmatter(text)
        if not frontmatter:
            return None
        data = _parse_simple_yaml(frontmatter)
        try:
            return KnowledgeNode(
                id=str(data["id"]),
                name=str(data.get("name") or data["id"]),
                description=str(data.get("description") or ""),
                type=str(data["type"]),
                source_tree_id=str(data["source_tree_id"]),
                source_fold_id=str(data.get("source_fold_id") or data.get("source_memory_id")),
                source_evidence_ids=_coerce_tags(data.get("source_evidence_ids")),
                created_at=str(data.get("created_at") or ""),
                updated_at=str(data.get("updated_at") or ""),
                confidence=float(data.get("confidence") or 0.6),
                status=str(data.get("status") or "active"),
                tags=_coerce_tags(data.get("tags")),
                content=content.strip(),
            )
        except (KeyError, ValueError):
            return None

    def _node_by_uri(self, uri: str) -> KnowledgeNode | None:
        parts = uri.removeprefix("mem://").split("/", 1)
        if len(parts) != 2:
            return None
        memory_type, memory_id = parts
        if memory_type not in LONG_TERM_MEMORY_TYPES:
            return None
        return self._read_knowledge(self._memory_path(memory_type, memory_id))

    def _memory_path(self, memory_type: str, memory_id: str) -> Path:
        return self.memories_root / memory_type / f"{_slugify(memory_id)}.md"

    def _to_context_result(self, node: KnowledgeNode, *, include_content: bool = True) -> dict[str, Any]:
        return {
            "uri": node.uri,
            "context_type": "knowledge",
            "title": node.name,
            "abstract": node.description,
            "overview": node.content if include_content else node.description,
            "trust_score": node.confidence,
            "status": node.status,
            "sensitivity": "public",
            "updated_at": node.updated_at,
            "tags": node.tags,
            "metadata": {
                "type": node.type,
                "source_tree_id": node.source_tree_id,
                "source_fold_id": node.source_fold_id,
                "source_memory_id": node.source_fold_id,
                "source_evidence_ids": node.source_evidence_ids,
                "confidence": node.confidence,
                "status": node.status,
            },
        }

    def _write_memory_index(self) -> None:
        lines = ["# Long-term Memory Index", ""]
        memories = [item for item in self._load_long_term_memories() if item.status == "active"] if self.memories_root.exists() else []
        for memory_type in ["user", "feedback", "project", "reference", "pattern"]:
            lines.append(f"## {memory_type}")
            bucket = [item for item in memories if item.type == memory_type]
            if bucket:
                for item in bucket:
                    lines.append(f"- {item.name} - {item.description} ({item.type})")
            else:
                lines.append("- (none)")
            lines.append("")
        self.memory_index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class TokenLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.last_input_tokens: int | None = None

    def record(self, model: str, usage: Any) -> None:
        input_tokens = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None)
        self.last_input_tokens = input_tokens
        data = {
            "ts": datetime.now(UTC8).isoformat(timespec="seconds"),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False) + "\n")

    def should_compact(self, max_context_tokens: int, threshold: float) -> bool:
        return self.last_input_tokens is not None and self.last_input_tokens >= int(max_context_tokens * threshold)

    def _iter_rows(self):
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue

    def stats_by_date(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for row in self._iter_rows() or []:
            date = row.get("ts", "")[:10] or "unknown"
            bucket = stats.setdefault(date, {"input_tokens": 0, "output_tokens": 0})
            bucket["input_tokens"] += row.get("input_tokens") or 0
            bucket["output_tokens"] += row.get("output_tokens") or 0
        return stats

    def stats_by_model(self) -> dict[str, dict[str, int]]:
        stats: dict[str, dict[str, int]] = {}
        for row in self._iter_rows() or []:
            model = row.get("model") or "unknown"
            bucket = stats.setdefault(model, {"input_tokens": 0, "output_tokens": 0})
            bucket["input_tokens"] += row.get("input_tokens") or 0
            bucket["output_tokens"] += row.get("output_tokens") or 0
        return stats


def _node_index_payload(node: KnowledgeNode) -> dict[str, Any]:
    data = asdict(node)
    data["content"] = ""
    return data


def _long_term_type_for_fold(item: Any) -> str:
    metadata = getattr(item, "metadata", {}) or {}
    special = metadata.get("long_term_special_type")
    if special == "user_profile":
        return "user"
    if special == "user_feedback":
        return "feedback"
    if special == "reference":
        return "reference"
    node_type = str(getattr(item, "node_type", getattr(item, "memory_type", "")))
    if node_type in {"hypothesis", "decision", "conclusion"}:
        return "pattern"
    return "project"


def _render_knowledge_markdown(node: KnowledgeNode) -> str:
    frontmatter = {
        "id": node.id,
        "name": node.name,
        "description": node.description,
        "type": node.type,
        "source_tree_id": node.source_tree_id,
        "source_fold_id": node.source_fold_id,
        "source_memory_id": node.source_fold_id,
        "source_evidence_ids": ",".join(node.source_evidence_ids),
        "created_at": node.created_at,
        "updated_at": node.updated_at,
        "confidence": node.confidence,
        "status": node.status,
        "tags": ",".join(node.tags),
    }
    lines = ["---"]
    lines.extend(f"{key}: {value}" for key, value in frontmatter.items())
    lines.extend(["---", "", node.content.strip(), ""])
    return "\n".join(lines)


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


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---", 4)
    if end < 0:
        return "", text
    return text[4:end].strip(), text[end + 4 :].strip()


def _parse_simple_yaml(text: str) -> dict[str, str]:
    data = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def _coerce_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return []


def _title_from_content(content: str) -> str:
    first = content.strip().splitlines()[0] if content.strip() else "Knowledge"
    return first[:60] + ("..." if len(first) > 60 else "")


def _slugify(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text[:96] or "memory"


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    tokens = set(raw)
    for token in raw:
        if len(token) > 3 and any("\u4e00" <= ch <= "\u9fff" for ch in token):
            tokens.update(token[i : i + 2] for i in range(len(token) - 1))
    return tokens


def _now() -> str:
    return datetime.now(UTC8).isoformat(timespec="seconds")
