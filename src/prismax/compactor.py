from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .model_client import TextBlock, ToolUseBlock


class HistoryCompactor:
    def __init__(
        self,
        *,
        client: Any,
        model: str,
        memory_store,
        token_log=None,
        keep_messages: int = 8,
        max_context_tokens: int = 64_000,
        threshold: float = 0.7,
        max_tokens: int = 1200,
        max_transcript_chars: int = 60_000,
    ) -> None:
        self.client = client
        self.model = model
        self.memory_store = memory_store
        self.token_log = token_log
        self.keep_messages = keep_messages
        self.max_context_tokens = max_context_tokens
        self.threshold = threshold
        self.max_tokens = max_tokens
        self.max_transcript_chars = max_transcript_chars

    def should_compact(self, history: list[dict[str, Any]]) -> bool:
        if len(history) <= self.keep_messages + 1:
            return False
        if self.token_log and self.token_log.should_compact(
            self.max_context_tokens, self.threshold
        ):
            return True
        return len(history) > self.keep_messages * 3

    def maybe_compact(self, history: list[dict[str, Any]]) -> bool:
        if not self.should_compact(history):
            return False
        return self.compact(history)

    def compact(self, history: list[dict[str, Any]]) -> bool:
        recent = _safe_recent_window(history, self.keep_messages)
        old_count = len(history) - len(recent)
        if old_count <= 0:
            return False

        transcript = _render_messages(history[:old_count], self.max_transcript_chars)
        if not transcript.strip():
            return False

        response = self.client.create_message(
            model=self.model,
            max_tokens=self.max_tokens,
            system=(
                "You compress agent conversation history. Preserve operational context, "
                "user intent, decisions, constraints, file changes, tool findings, user preferences, "
                "and open tasks."
            ),
            messages=[{"role": "user", "content": self._compact_prompt(transcript)}],
            tools=[],
        )
        if self.token_log:
            self.token_log.record(self.model, response.usage)

        summary = "\n".join(
            block.text for block in response.content if isinstance(block, TextBlock)
        ).strip()
        if not summary:
            return False

        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._write_compaction_outputs(stamp=stamp, summary=summary, old_count=old_count)
        history[:] = [
            {
                "role": "user",
                "content": (
                    "Earlier conversation was compressed. Use this summary as prior context:\n\n"
                    f"{summary}"
                ),
            },
            *recent,
        ]
        print(f"[compact] compressed {old_count} messages; kept {len(recent)} recent messages")
        return True

    def compact_startup(self, history: list[dict[str, Any]]) -> bool:
        if len(history) < 2:
            return False
        transcript = _render_messages(history, self.max_transcript_chars)
        response = self.client.create_message(
            model=self.model,
            max_tokens=self.max_tokens,
            system=(
                "You archive uncompressed conversation history into durable memory. "
                "Preserve useful project context and user preferences."
            ),
            messages=[{"role": "user", "content": self._compact_prompt(transcript)}],
            tools=[],
        )
        if self.token_log:
            self.token_log.record(self.model, response.usage)
        summary = "\n".join(
            block.text for block in response.content if isinstance(block, TextBlock)
        ).strip()
        if not summary:
            return False
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._write_compaction_outputs(stamp=stamp, summary=summary, old_count=len(history))
        print(f"[startup compact] archived {len(history)} uncompressed messages")
        return True

    def _write_compaction_outputs(self, *, stamp: str, summary: str, old_count: int) -> None:
        episode = _extract("episode", summary)
        updated_memory = _extract("updated_memory", summary)
        updated_user = _extract("updated_user", summary)

        if episode:
            self.memory_store.append_episode(episode)
        if updated_memory:
            self.memory_store.write_memory(updated_memory)
        if updated_user:
            self.memory_store.write_user(updated_user)

        self.memory_store.append_compaction(
            stamp=stamp,
            summary=summary,
            old_count=old_count,
            append_to_memory=not bool(updated_memory),
        )
        self.memory_store.append_compact_marker()

    def _compact_prompt(self, transcript: str) -> str:
        return (
            "Summarize the transcript below. Return exactly these XML-like sections:\n"
            "<episode>Concise chronological episode notes for today's work.</episode>\n"
            "<updated_memory>Updated long-term project memory. Preserve useful existing memory "
            "and add new goals, decisions, constraints, files, commands, and open tasks.</updated_memory>\n"
            "<updated_user>Updated durable user profile. Preserve useful existing preferences; "
            "add only stable preferences learned from the transcript.</updated_user>\n\n"
            "Current long-term memory:\n"
            f"{self.memory_store.read_memory() or '(empty)'}\n\n"
            "Current user profile:\n"
            f"{self.memory_store.read_user() or '(empty)'}\n\n"
            "Today's existing episode memory:\n"
            f"{self.memory_store.read_today_episode() or '(empty)'}\n\n"
            "Transcript:\n\n"
            f"{transcript}"
        )


def _extract(tag: str, text: str) -> str | None:
    match = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return match.group(1).strip() if match else None


def _safe_recent_window(history: list[dict[str, Any]], keep_messages: int) -> list[dict[str, Any]]:
    recent = list(history[-keep_messages:])
    while recent and (_is_tool_result_message(recent[0]) or _is_tool_use_message(recent[0])):
        recent.pop(0)
    return recent


def _is_tool_result_message(message: dict[str, Any]) -> bool:
    content = message.get("content")
    return (
        message.get("role") == "user"
        and isinstance(content, list)
        and any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content)
    )


def _is_tool_use_message(message: dict[str, Any]) -> bool:
    content = message.get("content")
    return (
        message.get("role") == "assistant"
        and isinstance(content, list)
        and any(isinstance(block, ToolUseBlock) for block in content)
    )


def _render_messages(messages: list[dict[str, Any]], max_chars: int) -> str:
    parts: list[str] = []
    total = 0
    for message in messages:
        rendered = f"{message.get('role', 'unknown').upper()}:\n{_render_content(message.get('content'))}"
        if total + len(rendered) > max_chars:
            remaining = max_chars - total
            if remaining > 0:
                parts.append(rendered[:remaining] + "\n...[truncated]")
            break
        parts.append(rendered)
        total += len(rendered)
    return "\n\n".join(parts)


def _render_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return repr(content)

    rendered: list[str] = []
    for block in content:
        if isinstance(block, TextBlock):
            rendered.append(block.text)
        elif isinstance(block, ToolUseBlock):
            rendered.append(f"[tool_use {block.name} id={block.id} input={block.input!r}]")
        elif isinstance(block, dict) and block.get("type") == "tool_result":
            rendered.append(
                f"[tool_result id={block.get('tool_use_id')}]\n{block.get('content', '')}"
            )
        else:
            rendered.append(repr(block))
    return "\n".join(rendered)
