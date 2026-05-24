from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ContextObject:
    uri: str
    context_type: str  # session|memory|resource|skill
    title: str
    abstract: str      # L0
    overview: str      # L1
    content_path: str  # L2 relative path from context root
    source: str
    trust_score: float
    sensitivity: str   # public|internal|sensitive
    status: str        # active|quarantine|archived
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    digest: str = ""
    created_at: str = ""
    updated_at: str = ""
    ttl: str | None = None


def _compute_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _uri_to_path(uri: str) -> str:
    """mem://user/profile -> mem/user/profile"""
    return re.sub(r"^(\w+)://", r"\1/", uri)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ContextFS:
    def __init__(self, memory_dir: Path) -> None:
        self.memory_dir = Path(memory_dir)
        self.root = self.memory_dir / "context"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.jsonl"
        self.diffs_path = self.root / "diffs.jsonl"
        if not self.index_path.exists():
            self.index_path.write_text("", encoding="utf-8")
        if not self.diffs_path.exists():
            self.diffs_path.write_text("", encoding="utf-8")

    # ---- write ----

    def write_object(self, obj: ContextObject, content: str) -> str:
        now = _now_iso()
        if not obj.created_at:
            obj.created_at = now
        obj.updated_at = now
        obj.digest = _compute_digest(content)
        if not obj.content_path:
            obj.content_path = _uri_to_path(obj.uri) + ".md"

        # write L2
        l2_path = self.root / obj.content_path
        l2_path.parent.mkdir(parents=True, exist_ok=True)
        l2_path.write_text(content, encoding="utf-8")

        # upsert index
        self._upsert_index(obj)
        return obj.uri

    def _upsert_index(self, obj: ContextObject) -> None:
        lines = self._read_index_lines()
        data = asdict(obj)
        found = False
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("uri") == obj.uri:
                lines[i] = json.dumps(data, ensure_ascii=False)
                found = True
                break
        if not found:
            lines.append(json.dumps(data, ensure_ascii=False))
        self.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ---- read ----

    def read_object(self, uri: str, layer: str = "auto") -> dict[str, Any]:
        entry = self._find_index_entry(uri)
        if entry is None:
            raise KeyError(f"URI not found: {uri}")
        if layer == "auto":
            content = entry.get("overview", "") or entry.get("abstract", "")
        elif layer == "full":
            l2_path = self.root / entry.get("content_path", "")
            content = l2_path.read_text(encoding="utf-8") if l2_path.exists() else ""
        else:
            content = entry.get(layer, "")
        return {"uri": uri, "content": content, **entry}

    # ---- list ----

    def list_objects(self, prefix: str = "", limit: int = 50) -> list[dict[str, Any]]:
        results = []
        for line in self._read_index_lines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if prefix and not entry.get("uri", "").startswith(prefix):
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    # ---- search ----

    def search_objects(self, query: str, limit: int = 5, *, include_sensitive: bool = False) -> list[dict[str, Any]]:
        tokens = query.lower().split()
        scored = []
        for line in self._read_index_lines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if not include_sensitive:
                if entry.get("sensitivity") == "sensitive":
                    continue
                if entry.get("status") == "quarantine":
                    continue
                ttl = entry.get("ttl")
                if ttl and _is_expired(ttl):
                    continue

            score = 0.0
            title = (entry.get("title") or "").lower()
            abstract = (entry.get("abstract") or "").lower()
            overview = (entry.get("overview") or "").lower()
            uri = (entry.get("uri") or "").lower()
            tags = " ".join(entry.get("tags") or []).lower()

            for token in tokens:
                if token in title:
                    score += 5
                elif token in tags:
                    score += 4
                elif token in abstract:
                    score += 3
                elif token in overview:
                    score += 2
                elif token in uri:
                    score += 1

            # L2 full-text search
            l2_path = self.root / (entry.get("content_path") or "")
            if l2_path.exists():
                l2_text = l2_path.read_text(encoding="utf-8").lower()
                for token in tokens:
                    if token in l2_text:
                        score += 1

            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: (-x[0], -(x[1].get("trust_score") or 0)))
        return [entry for _, entry in scored[:limit]]

    # ---- diff ----

    def append_diff(self, entry: dict[str, Any]) -> None:
        entry.setdefault("ts", _now_iso())
        with self.diffs_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ---- internals ----

    def _read_index_lines(self) -> list[str]:
        if not self.index_path.exists():
            return []
        text = self.index_path.read_text(encoding="utf-8")
        return text.splitlines()

    def _find_index_entry(self, uri: str) -> dict[str, Any] | None:
        for line in self._read_index_lines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("uri") == uri:
                return entry
        return None


def _is_expired(ttl: str) -> bool:
    try:
        expiry = datetime.fromisoformat(ttl)
        return datetime.now(timezone.utc) > expiry
    except ValueError:
        return False
