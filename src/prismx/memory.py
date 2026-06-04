from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UTC8 = timezone(timedelta(hours=8))

LONG_TERM_MEMORY_TYPES = {"user", "feedback", "project", "reference"}

CATEGORY_TO_LONG_TERM_TYPE = {
    "profile": "user",
    "preferences": "feedback",
    "entities": "user",
    "events": "project",
    "decisions": "project",
    "constraints": "project",
    "open_tasks": "project",
    "cases": "project",
    "patterns": "project",
    "tools": "reference",
    "skills": "reference",
    "research": "reference",
}


@dataclass
class LongTermMemory:
    id: str
    name: str
    description: str
    type: str
    source_tree_id: str
    source_memory_id: str
    created_at: str
    updated_at: str
    confidence: float = 0.6
    status: str = "active"
    tags: list[str] | None = None
    content: str = ""

    @property
    def uri(self) -> str:
        return f"mem://{self.type}/{self.id}"


class MemoryStore:
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
        for memory_type in LONG_TERM_MEMORY_TYPES:
            (self.memories_root / memory_type).mkdir(parents=True, exist_ok=True)
        self.memory_index_path = self.memory_dir / "MEMORY.md"

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
        confidence: float = 0.8,
        tags: list[str] | None = None,
    ) -> str:
        note = note.strip()
        if not note or not source_tree_id or not source_memory_id:
            return ""
        memory_type = CATEGORY_TO_LONG_TERM_TYPE.get(category, "project")
        now = datetime.now(UTC8).isoformat()
        memory = LongTermMemory(
            id=_slugify(f"{source_tree_id}-{source_memory_id}"),
            name=title or (note[:60] + "..." if len(note) > 60 else note),
            description=note[:200],
            type=memory_type,
            source_tree_id=source_tree_id,
            source_memory_id=source_memory_id,
            created_at=now,
            updated_at=now,
            confidence=float(confidence),
            status="active",
            tags=tags or [category],
            content=note,
        )
        return self._write_long_term_memory(memory)

    def promote_tree_memory(self, item: Any, *, memory_type: str | None = None) -> str:
        source_tree_id = str(getattr(item, "tree_id", ""))
        source_memory_id = str(getattr(item, "id", ""))
        if not source_tree_id or not source_memory_id:
            return ""
        target_type = memory_type or _long_term_type_for_tree_memory(item)
        if target_type not in LONG_TERM_MEMORY_TYPES:
            target_type = "project"
        now = datetime.now(UTC8).isoformat()
        memory = LongTermMemory(
            id=_slugify(f"{source_tree_id}-{source_memory_id}"),
            name=str(getattr(item, "title", "") or getattr(item, "content", "")[:60] or source_memory_id),
            description=str(getattr(item, "content", ""))[:200],
            type=target_type,
            source_tree_id=source_tree_id,
            source_memory_id=source_memory_id,
            created_at=now,
            updated_at=now,
            confidence=float(getattr(item, "confidence", 0.6)),
            status="active",
            tags=list(getattr(item, "tags", []) or []) + [str(getattr(item, "memory_type", "finding"))],
            content=str(getattr(item, "content", "")),
        )
        return self._write_long_term_memory(memory)

    def commit_session_archive(
        self, session_uri: str, summary: str, operations: list[dict[str, Any]], metadata: dict[str, Any]
    ) -> str:
        self.last_committed_knowledge_uris = []
        for op in operations:
            if op.get("action") not in {"upsert", "append"}:
                continue
            source_tree_id = str(op.get("source_tree_id") or "")
            source_memory_id = str(op.get("source_memory_id") or "")
            memory_type = str(op.get("type") or op.get("long_term_type") or "project")
            if memory_type not in LONG_TERM_MEMORY_TYPES or not source_tree_id or not source_memory_id:
                continue
            now = datetime.now(UTC8).isoformat()
            memory = LongTermMemory(
                id=_slugify(f"{source_tree_id}-{source_memory_id}"),
                name=str(op.get("title") or op.get("name") or op.get("key") or source_memory_id),
                description=str(op.get("abstract") or op.get("overview") or "")[:200],
                type=memory_type,
                source_tree_id=source_tree_id,
                source_memory_id=source_memory_id,
                created_at=now,
                updated_at=now,
                confidence=float(op.get("trust_score") or op.get("confidence") or 0.6),
                status="active",
                tags=list(op.get("tags") or []),
                content=str(op.get("content") or op.get("overview") or ""),
            )
            uri = self._write_long_term_memory(memory)
            if uri:
                self.last_committed_knowledge_uris.append(uri)
        return session_uri

    def search_memory(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        selected = self._search_long_term(query, limit=limit)
        if selected:
            return selected
        return self._legacy_search(query, limit=limit)

    def read_context(self, uri: str, layer: str = "auto") -> str:
        memory = self._memory_by_uri(uri)
        if memory is not None:
            if layer in {"l0", "metadata"}:
                return memory.description
            return memory.content
        return f"Error: URI not found: {uri}"

    def list_context(self, prefix: str = "mem://", limit: int = 50) -> list[dict[str, Any]]:
        items = [self._to_context_result(memory) for memory in self._load_long_term_memories()]
        if prefix:
            items = [item for item in items if str(item.get("uri", "")).startswith(prefix)]
        if items:
            return items[:limit]
        return []

    def graph_neighbors(self, uri: str, limit: int = 5) -> list[dict[str, Any]]:
        return []

    def render_memory(self) -> str:
        lines = ["# Long-term Memory"]
        for memory_type in ["user", "feedback", "project", "reference"]:
            lines.append(f"\n## {memory_type}")
            items = [item for item in self._load_long_term_memories() if item.type == memory_type]
            if not items:
                lines.append("- (none)")
                continue
            for item in items:
                lines.append(f"- [{item.name}]({item.uri}) trust={item.confidence:.1f}")
        return "\n".join(lines)

    def _write_long_term_memory(self, memory: LongTermMemory) -> str:
        if memory.type not in LONG_TERM_MEMORY_TYPES or not memory.source_tree_id or not memory.source_memory_id:
            return ""
        path = self._memory_path(memory.type, memory.id)
        existing = self._read_long_term_memory(path)
        if existing is not None:
            memory.created_at = existing.created_at
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_long_term_markdown(memory), encoding="utf-8")
        self._write_memory_index()
        return memory.uri

    def _search_long_term(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        tokens = _tokens(query)
        scored: list[tuple[float, LongTermMemory]] = []
        for memory in self._load_long_term_memories():
            if memory.status != "active":
                continue
            haystacks = {
                "name": memory.name.lower(),
                "description": memory.description.lower(),
                "type": memory.type.lower(),
                "tags": " ".join(memory.tags or []).lower(),
            }
            score = 0.0
            for token in tokens:
                if token in haystacks["name"]:
                    score += 5
                if token in haystacks["description"]:
                    score += 3
                if token in haystacks["type"]:
                    score += 2
                if token in haystacks["tags"]:
                    score += 2
            if score > 0:
                scored.append((score + memory.confidence, memory))
        scored.sort(key=lambda pair: (-pair[0], pair[1].updated_at))
        return [self._to_context_result(memory, include_content=True) for _, memory in scored[:limit]]

    def _legacy_search(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        return []

    def _load_long_term_memories(self) -> list[LongTermMemory]:
        memories = []
        for memory_type in sorted(LONG_TERM_MEMORY_TYPES):
            for path in sorted((self.memories_root / memory_type).glob("*.md")):
                memory = self._read_long_term_memory(path)
                if memory is not None:
                    memories.append(memory)
        return sorted(memories, key=lambda item: item.updated_at, reverse=True)

    def _read_long_term_memory(self, path: Path) -> LongTermMemory | None:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        frontmatter, content = _split_frontmatter(text)
        if not frontmatter:
            return None
        data = _parse_simple_yaml(frontmatter)
        try:
            return LongTermMemory(
                id=str(data["id"]),
                name=str(data.get("name") or data["id"]),
                description=str(data.get("description") or ""),
                type=str(data["type"]),
                source_tree_id=str(data["source_tree_id"]),
                source_memory_id=str(data["source_memory_id"]),
                created_at=str(data.get("created_at") or ""),
                updated_at=str(data.get("updated_at") or ""),
                confidence=float(data.get("confidence") or 0.6),
                status=str(data.get("status") or "active"),
                tags=_coerce_tags(data.get("tags")),
                content=content.strip(),
            )
        except KeyError:
            return None

    def _memory_by_uri(self, uri: str) -> LongTermMemory | None:
        parts = uri.removeprefix("mem://").split("/", 1)
        if len(parts) != 2:
            return None
        memory_type, memory_id = parts
        if memory_type not in LONG_TERM_MEMORY_TYPES:
            return None
        return self._read_long_term_memory(self._memory_path(memory_type, memory_id))

    def _memory_path(self, memory_type: str, memory_id: str) -> Path:
        return self.memories_root / memory_type / f"{_slugify(memory_id)}.md"

    def _to_context_result(self, memory: LongTermMemory, *, include_content: bool = True) -> dict[str, Any]:
        return {
            "uri": memory.uri,
            "context_type": "knowledge",
            "title": memory.name,
            "abstract": memory.description,
            "overview": memory.content if include_content else memory.description,
            "trust_score": memory.confidence,
            "status": memory.status,
            "sensitivity": "public",
            "updated_at": memory.updated_at,
            "tags": memory.tags or [],
            "metadata": {
                "type": memory.type,
                "source_tree_id": memory.source_tree_id,
                "source_memory_id": memory.source_memory_id,
                "confidence": memory.confidence,
                "status": memory.status,
            },
        }

    def _write_memory_index(self) -> None:
        lines = ["# Long-term Memory Index", ""]
        memories: list[LongTermMemory] = []
        if self.memories_root.exists():
            memories = [item for item in self._load_long_term_memories() if item.status == "active"]
        for memory_type in ["user", "feedback", "project", "reference"]:
            lines.append(f"## {memory_type}")
            bucket = [item for item in memories if item.type == memory_type]
            if bucket:
                for item in bucket:
                    lines.append(f"- {item.name} - {item.description} ({item.type})")
            else:
                lines.append("- (none)")
            lines.append("")
        self.memory_index_path.parent.mkdir(parents=True, exist_ok=True)
        self.memory_index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


class TokenLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.last_input_tokens: int | None = None

    def record(self, model: str, usage: Any) -> None:
        input_tokens = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None) or getattr(
            usage, "completion_tokens", None
        )
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
        if self.last_input_tokens is None:
            return False
        return self.last_input_tokens >= int(max_context_tokens * threshold)

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


def _long_term_type_for_tree_memory(item: Any) -> str:
    metadata = getattr(item, "metadata", {}) or {}
    special = metadata.get("long_term_special_type")
    if special == "user_profile":
        return "user"
    if special == "user_feedback":
        return "feedback"
    if special == "reference":
        return "reference"
    return "project"


def _render_long_term_markdown(memory: LongTermMemory) -> str:
    frontmatter = {
        "id": memory.id,
        "name": memory.name,
        "description": memory.description,
        "type": memory.type,
        "source_tree_id": memory.source_tree_id,
        "source_memory_id": memory.source_memory_id,
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
        "confidence": memory.confidence,
        "status": memory.status,
        "tags": ",".join(memory.tags or []),
    }
    lines = ["---"]
    lines.extend(f"{key}: {value}" for key, value in frontmatter.items())
    lines.extend(["---", "", memory.content.strip(), ""])
    return "\n".join(lines)


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


def _slugify(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text[:80] or "memory"


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    tokens = set(raw)
    for token in raw:
        if len(token) > 3 and any("\u4e00" <= ch <= "\u9fff" for ch in token):
            tokens.update(token[i : i + 2] for i in range(len(token) - 1))
    return tokens
