from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WIKI_BUCKETS = {
    "decisions": "Project",
    "constraints": "Project",
    "open_tasks": "Project",
    "tools": "Architecture",
    "skills": "Architecture",
    "profile": "User",
    "preferences": "User",
    "entities": "User",
    "events": "User",
    "cases": "Pattern",
    "patterns": "Pattern",
    "research": "Research",
}


@dataclass
class KnowledgeObject:
    title: str
    summary: str
    content: str
    source_session: str
    source_branch: str
    source_compaction: str
    trust_score: float
    tags: list[str] = field(default_factory=list)
    updated_at: str = ""
    knowledge_type: str = "project"
    uri: str = ""


class WikiKnowledgeBase:
    def __init__(self, memory_dir: Path) -> None:
        self.root = Path(memory_dir) / "Wiki"
        for bucket in {"Project", "Architecture", "User", "Pattern", "Research"}:
            (self.root / bucket).mkdir(parents=True, exist_ok=True)

    def write(self, obj: KnowledgeObject, *, category: str = "decisions", key: str = "") -> Path:
        if not obj.updated_at:
            obj.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        bucket = WIKI_BUCKETS.get(category, "Project")
        slug = _slugify(key or obj.title)
        path = self.root / bucket / f"{slug}.md"
        obj.uri = obj.uri or f"wiki://{bucket}/{slug}"
        path.write_text(_render_knowledge_markdown(obj), encoding="utf-8")
        return path


class LocalSemanticVectorIndex:
    def __init__(self, memory_dir: Path) -> None:
        self.path = Path(memory_dir) / "semantic_index.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def upsert(self, obj: KnowledgeObject, *, path: Path) -> None:
        rows = self._read_rows()
        tokens = sorted(_tokens(" ".join([obj.title, obj.summary, obj.content, " ".join(obj.tags)])))
        record = {
            "uri": obj.uri,
            "path": str(path),
            "title": obj.title,
            "summary": obj.summary,
            "tokens": tokens,
            "trust_score": obj.trust_score,
            "knowledge_type": obj.knowledge_type,
            "source_session": obj.source_session,
            "source_branch": obj.source_branch,
            "source_compaction": obj.source_compaction,
            "tags": obj.tags,
            "updated_at": obj.updated_at,
        }
        replaced = False
        for index, row in enumerate(rows):
            if row.get("uri") == obj.uri:
                rows[index] = record
                replaced = True
                break
        if not replaced:
            rows.append(record)
        self.path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
            encoding="utf-8",
        )

    def search(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        scored = []
        for row in self._read_rows():
            tokens = set(row.get("tokens") or [])
            overlap = len(tokens & query_tokens)
            if overlap <= 0:
                continue
            score = overlap + float(row.get("trust_score") or 0)
            result = {
                "uri": row.get("uri", ""),
                "title": row.get("title", ""),
                "abstract": row.get("summary", ""),
                "overview": row.get("summary", ""),
                "trust_score": row.get("trust_score", 0.0),
                "status": "active",
                "sensitivity": "public",
                "updated_at": row.get("updated_at", ""),
                "context_type": "knowledge",
                "tags": row.get("tags", []),
                "metadata": {
                    "source_session": row.get("source_session", ""),
                    "source_branch": row.get("source_branch", ""),
                    "source_compaction": row.get("source_compaction", ""),
                    "knowledge_type": row.get("knowledge_type", ""),
                    "semantic_score": score,
                    "wiki_path": row.get("path", ""),
                },
            }
            scored.append((score, result))
        scored.sort(key=lambda item: (-item[0], -float(item[1].get("trust_score") or 0)))
        return [item for _, item in scored[:limit]]

    def _read_rows(self) -> list[dict[str, Any]]:
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows


def _render_knowledge_markdown(obj: KnowledgeObject) -> str:
    metadata = {
        "title": obj.title,
        "summary": obj.summary,
        "source_session": obj.source_session,
        "source_branch": obj.source_branch,
        "source_compaction": obj.source_compaction,
        "trust_score": obj.trust_score,
        "tags": obj.tags,
        "updated_at": obj.updated_at,
        "knowledge_type": obj.knowledge_type,
    }
    return "\n".join(
        [
            "---",
            json.dumps(metadata, ensure_ascii=False, indent=2),
            "---",
            "",
            f"# {obj.title}",
            "",
            "## Summary",
            obj.summary,
            "",
            "## Content",
            obj.content,
            "",
        ]
    )


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s一-鿿-]", "", text)
    text = re.sub(r"\s+", "-", text)
    return text[:80] or "knowledge"


def _tokens(text: str) -> set[str]:
    raw = re.findall(r"[\w一-鿿]+", text.lower())
    tokens = set(raw)
    for token in raw:
        if len(token) > 3 and any("\u4e00" <= ch <= "\u9fff" for ch in token):
            tokens.update(token[i : i + 2] for i in range(len(token) - 1))
    return tokens
