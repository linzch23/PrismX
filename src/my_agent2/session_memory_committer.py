from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol


class MemoryExtractor(Protocol):
    def extract(self, *, session_uri: str, summary: str, metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        ...


class LlmMemoryExtractor:
    def __init__(self, client: Any, model: str, *, max_tokens: int = 1200) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    def extract(self, *, session_uri: str, summary: str, metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        prompt = _extraction_prompt(session_uri, summary, metadata)
        try:
            response = self.client.create_message(
                model=self.model, max_tokens=self.max_tokens,
                system="You extract structured long-term memory operations from conversation summaries. Output ONLY valid JSON.",
                messages=[{"role": "user", "content": prompt}], tools=[],
            )
            text = "\n".join(
                getattr(block, "text", "")
                for block in (response.content if hasattr(response, "content") else [])
            )
            operations = _parse_extraction_json(text)
            return operations, None
        except Exception as e:
            return [], f"extraction_failed: {e}"


class NoopMemoryExtractor:
    def extract(self, *, session_uri: str, summary: str, metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        return [], None


class SessionMemoryCommitter:
    def __init__(self, tree: Any, memory_store: Any, extractor: MemoryExtractor) -> None:
        self.tree = tree
        self.memory_store = memory_store
        self.extractor = extractor

    def commit_compaction(self, session_id: str, compaction_id: str) -> str:
        # Read compaction entry
        branch = self.tree.getBranch(session_id)
        entry = next((e for e in branch if isinstance(e, dict) and e.get("id") == compaction_id
                      or hasattr(e, "id") and e.id == compaction_id), None)
        if entry is None:
            raise ValueError(f"Compaction entry {compaction_id} not found in session {session_id}")

        if isinstance(entry, dict):
            summary = entry.get("summary", "")
            compacted_ids = entry.get("compactedEntryIds", [])
            first_kept = entry.get("firstKeptEntryId", "")
            token_before = entry.get("tokenEstimateBefore", 0)
            token_after = entry.get("tokenEstimateAfter", 0)
        else:
            summary = entry.summary
            compacted_ids = entry.compactedEntryIds
            first_kept = entry.firstKeptEntryId
            token_before = entry.tokenEstimateBefore
            token_after = entry.tokenEstimateAfter

        # Debug info
        try:
            debug = self.tree.debugBuildModelContext(session_id)
        except Exception:
            debug = {}

        # Generate archive URI
        now = datetime.now(timezone.utc)
        date_part = now.strftime("%Y/%m/%d")
        archive_uri = f"ctx://sessions/archives/{date_part}/{session_id}-{compaction_id}"

        metadata = {
            "session_id": session_id,
            "compaction_id": compaction_id,
            "compactedEntryIds": compacted_ids,
            "firstKeptEntryId": first_kept,
            "tokenEstimateBefore": token_before,
            "tokenEstimateAfter": token_after,
            "debug": debug,
        }

        # Extract memory operations
        operations, error = self.extractor.extract(
            session_uri=archive_uri, summary=summary, metadata=metadata,
        )
        if error:
            metadata["extraction_error"] = error

        # Commit
        self.memory_store.commit_session_archive(
            session_uri=archive_uri,
            summary=summary,
            operations=operations,
            metadata=metadata,
        )
        return archive_uri


def _extraction_prompt(session_uri: str, summary: str, metadata: dict[str, Any]) -> str:
    return f"""Extract durable long-term memory operations from this conversation summary.

Session: {session_uri}
Summary:
{summary}

Output a JSON object with an "operations" array. Each operation:
{{
  "action": "upsert" | "append" | "quarantine",
  "category": "profile" | "preferences" | "entities" | "events" | "decisions" | "constraints" | "open_tasks" | "cases" | "patterns" | "tools" | "skills",
  "key": "stable-slug-for-dedup",
  "title": "short title",
  "abstract": "one sentence summary",
  "overview": "injectable overview (2-4 sentences)",
  "content": "full detail body",
  "reason": "why this belongs in long-term memory",
  "trust_score": 0.0-1.0,
  "tags": ["optional-tags"],
  "links": [
    {{
      "target_uri": "mem://...",
      "relation": "supports|contradicts|updates|related|derived_from|uses_tool",
      "confidence": 0.0-1.0,
      "reason": "why these are related"
    }}
  ]
}}

Only include items that have durable value beyond this session. Skip transient debugging details.
Output ONLY the JSON object, no other text."""


def _parse_extraction_json(text: str) -> list[dict[str, Any]]:
    text = text.strip()
    # Try to find JSON block
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        text = text[start:end].strip()
    # Find outermost { }
    if "{" in text and "}" in text:
        start = text.index("{")
        end = text.rindex("}") + 1
        text = text[start:end]
    data = json.loads(text)
    return data.get("operations", [])
