from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


UTC8 = timezone(timedelta(hours=8))


class MemoryStore:
    def __init__(self, memory_dir: Path, user_file: Path | None = None) -> None:
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.history_path = self.memory_dir / "history.jsonl"
        self.memory_path = self.memory_dir / "MEMORY.md"
        self.compactions_path = self.memory_dir / "compactions.md"
        self.user_file = user_file or self.memory_dir / "USER.md"
        if not self.memory_path.exists():
            self.memory_path.write_text("# Long-term Memory\n\n", encoding="utf-8")
        if not self.compactions_path.exists():
            self.compactions_path.write_text("# Conversation Compactions\n\n", encoding="utf-8")
        if not self.user_file.exists():
            self.user_file.parent.mkdir(parents=True, exist_ok=True)
            self.user_file.write_text("# User Profile\n\n", encoding="utf-8")

    def append_history(self, role: str, content: Any) -> None:
        record = {
            "ts": datetime.now(UTC8).isoformat(timespec="seconds"),
            "role": role,
            "content": content if isinstance(content, str) else repr(content),
        }
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_memory(self) -> str:
        return self.memory_path.read_text(encoding="utf-8").strip()

    def write_memory(self, content: str) -> None:
        self.memory_path.write_text(content.strip() + "\n", encoding="utf-8")

    def append_memory(self, note: str) -> None:
        note = note.strip()
        if not note:
            return
        with self.memory_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n- {note}\n")

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

    def append_compaction(
        self,
        *,
        stamp: str,
        summary: str,
        old_count: int,
        append_to_memory: bool = False,
    ) -> None:
        summary = summary.strip()
        with self.compactions_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## {stamp} ({old_count} messages)\n\n{summary}\n")
        if append_to_memory:
            with self.memory_path.open("a", encoding="utf-8") as handle:
                handle.write(f"\n## Compressed Context: {stamp}\n\n{summary}\n")

    def append_compact_marker(self) -> None:
        record = {"ts": datetime.now(UTC8).isoformat(timespec="seconds"), "type": "compact_event"}
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_unarchived_history(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        rows = []
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        last_marker = -1
        for index, row in enumerate(rows):
            if row.get("type") == "compact_event":
                last_marker = index
        return [
            {"role": row["role"], "content": row["content"]}
            for row in rows[last_marker + 1 :]
            if "role" in row and "content" in row
        ]


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
