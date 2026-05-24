from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TREE_ENTRY_TYPES = {
    "message",
    "tool_call",
    "tool_result",
    "branch_summary",
    "compaction",
    "label",
    "raw",
    "custom",
}
FILE_MUTATION_TOOLS = {"write_file", "edit_file"}


def load_session_records(
    session_id: str,
    session_dir: Path | None = None,
) -> list[dict[str, Any]]:
    session_id = _safe_session_id(session_id)
    session_dir = session_dir or Path("sessions")
    path = session_dir / f"{session_id}.jsonl"
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"session not found: {session_id}")

    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL in {path.name}:{line_number}: {exc}") from exc
        if isinstance(record, dict):
            records.append(record)
    return records


def list_session_summaries(session_dir: Path | None = None) -> list[dict[str, Any]]:
    session_dir = session_dir or Path("sessions")
    if not session_dir.exists():
        return []
    summaries = []
    for path in sorted(session_dir.glob("*.jsonl")):
        records = load_session_records(path.stem, session_dir)
        summaries.append(_session_summary(path.stem, path, records))
    return sorted(
        summaries,
        key=lambda item: (str(item.get("updatedAt") or ""), str(item.get("id") or "")),
    )


def records_to_run_steps(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_results = _tool_results_by_use_id(records)
    steps: list[dict[str, Any]] = []

    for record in records:
        record_type = record.get("type")
        if record_type == "message":
            message = record.get("message") or {}
            role = str(message.get("role") or "assistant")
            content = message.get("content")
            summary = _preview_text(content, 180)
            tool_calls = [
                _tool_call_payload(block, tool_results)
                for block in _tool_use_blocks(content)
            ]
            title = "User request" if role == "user" else "Assistant response"
            steps.append(
                {
                    "id": _record_id(record),
                    "nodeId": _record_id(record),
                    "kind": "user" if role == "user" else "assistant",
                    "title": title,
                    "status": "done",
                    "summary": summary,
                    "output": _content_text(content) or None,
                    "toolCalls": tool_calls,
                    "createdAt": record.get("timestamp"),
                }
            )
        elif record_type == "tool_call":
            tool_call = record.get("toolCall") or {}
            tool_payload = _tool_call_payload(tool_call, tool_results)
            steps.append(
                {
                    "id": _record_id(record),
                    "nodeId": _record_id(record),
                    "kind": "tool",
                    "title": f"Tool: {tool_payload['name'] or 'unknown'}",
                    "status": tool_payload["status"],
                    "summary": _tool_summary(tool_payload),
                    "output": tool_payload["output"],
                    "toolCalls": [tool_payload],
                    "createdAt": record.get("timestamp"),
                }
            )
        elif record_type in {"branch_summary", "compaction"}:
            summary = str(record.get("summary") or "")
            title = "Compaction checkpoint" if record_type == "compaction" else "Branch summary"
            steps.append(
                {
                    "id": _record_id(record),
                    "nodeId": _record_id(record),
                    "kind": "checkpoint",
                    "title": title,
                    "status": "done",
                    "summary": _preview_text(summary, 180),
                    "output": summary or None,
                    "toolCalls": [],
                    "createdAt": record.get("timestamp"),
                }
            )
        elif record_type == "label":
            label = str(record.get("label") or "")
            steps.append(
                {
                    "id": _record_id(record),
                    "nodeId": _record_id(record),
                    "kind": "checkpoint",
                    "title": "Label",
                    "status": "done",
                    "summary": label or "Label updated",
                    "output": json.dumps(record, ensure_ascii=False, indent=2),
                    "toolCalls": [],
                    "createdAt": record.get("timestamp"),
                }
            )
    return steps


def records_to_tree_nodes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active_leaf_id = _active_leaf_id(records)
    labels = _labels_by_target(records)
    nodes = []
    for record in records:
        record_type = str(record.get("type") or "")
        if record_type not in TREE_ENTRY_TYPES:
            continue
        node_id = _record_id(record)
        nodes.append(
            {
                "id": node_id,
                "parentId": record.get("parentId"),
                "type": record_type,
                "label": labels.get(node_id) or _node_label(record),
                "status": "active" if node_id == active_leaf_id else "normal",
                "children": [],
                "preview": _record_preview(record),
                "createdAt": record.get("timestamp"),
            }
        )
    return nodes


def records_to_file_changes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_results = _tool_results_by_use_id(records)
    by_path: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("type") != "tool_call":
            continue
        tool_call = record.get("toolCall") or {}
        name = str(tool_call.get("name") or "")
        if name not in FILE_MUTATION_TOOLS:
            continue
        tool_input = tool_call.get("input") or {}
        path = str(tool_input.get("path") or "").strip()
        if not path:
            continue
        output = _output_for_tool_call(tool_call, tool_results) or ""
        change_type = _change_type(name, output)
        by_path[path] = {
            "path": path,
            "type": change_type,
            "operation": "created/modified" if name == "write_file" else change_type,
            "additions": 0,
            "deletions": 0,
            "tool": name,
            "nodeId": record.get("id"),
            "createdAt": record.get("timestamp"),
        }
    return list(by_path.values())


def records_to_tool_events(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_results = _tool_results_by_use_id(records)
    events = []
    for record in records:
        if record.get("type") != "tool_call":
            continue
        tool_call = record.get("toolCall") or {}
        payload = _tool_call_payload(tool_call, tool_results)
        events.append(
            {
                "id": record.get("id") or payload["id"],
                "toolUseId": payload["id"],
                "name": payload["name"],
                "input": payload["input"],
                "output": payload["output"],
                "status": payload["status"],
                "target": _tool_target(payload["name"], payload["input"]),
                "createdAt": record.get("timestamp"),
            }
        )
    return events


def records_to_node_detail(records: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    by_id = {str(record.get("id")): record for record in records if record.get("id") is not None}
    record = by_id.get(node_id)
    if record is None:
        raise KeyError(f"node not found: {node_id}")
    children = [item.get("id") for item in records if item.get("parentId") == node_id]
    active_path = set(_active_path_ids(records))
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return {
        "nodeId": node_id,
        "record": record,
        "parentId": record.get("parentId"),
        "childrenIds": children,
        "contextLayer": metadata.get("contextLayer"),
        "onActivePath": node_id in active_path,
        "activeLeafId": _active_leaf_id(records),
        "preview": _record_preview(record),
    }


def memory_payload(memory_dir: Path | None = None) -> dict[str, Any]:
    memory_dir = memory_dir or Path("memory")
    path = memory_dir / "MEMORY.md"
    if not path.exists():
        return {"exists": False, "memory": ""}
    return {"exists": True, "memory": path.read_text(encoding="utf-8")}


def _safe_session_id(session_id: str) -> str:
    session_id = str(session_id).strip()
    if not session_id or "/" in session_id or "\\" in session_id or session_id in {".", ".."}:
        raise ValueError(f"invalid session id: {session_id!r}")
    return session_id


def _session_summary(session_id: str, path: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    info = next((record for record in records if record.get("type") == "session_info"), {})
    return {
        "id": session_id,
        "filePath": str(path),
        "title": info.get("title"),
        "recordCount": len(records),
        "createdAt": info.get("createdAt") or (records[0].get("timestamp") if records else None),
        "updatedAt": _latest_timestamp(records),
        "activeLeafId": _active_leaf_id(records),
    }


def _latest_timestamp(records: list[dict[str, Any]]) -> str | None:
    for record in reversed(records):
        if record.get("timestamp"):
            return str(record["timestamp"])
    return None


def _record_id(record: dict[str, Any]) -> str:
    return str(record.get("id") or "")


def _active_leaf_id(records: list[dict[str, Any]]) -> str | None:
    for record in reversed(records):
        if record.get("type") == "session_state" and record.get("activeLeafId"):
            return str(record["activeLeafId"])
        if record.get("type") == "session_info" and record.get("activeLeafId"):
            return str(record["activeLeafId"])
    for record in reversed(records):
        if record.get("type") in TREE_ENTRY_TYPES:
            return str(record.get("id"))
    return None


def _active_path_ids(records: list[dict[str, Any]]) -> list[str]:
    by_id = {str(record.get("id")): record for record in records if record.get("id") is not None}
    current = _active_leaf_id(records)
    path = []
    while current and current in by_id:
        path.append(current)
        parent = by_id[current].get("parentId")
        current = str(parent) if parent else None
    return list(reversed(path))


def _labels_by_target(records: list[dict[str, Any]]) -> dict[str, str]:
    labels = {}
    for record in records:
        if record.get("type") == "label" and record.get("targetId"):
            labels[str(record["targetId"])] = str(record.get("label") or "")
    return labels


def _tool_results_by_use_id(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    results = {}
    for record in records:
        if record.get("type") != "tool_result":
            continue
        result = record.get("toolResult") or {}
        use_id = result.get("tool_use_id")
        if use_id:
            results[str(use_id)] = result
    return results


def _tool_use_blocks(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    blocks = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            blocks.append(block)
    return blocks


def _tool_call_payload(
    tool_call: dict[str, Any],
    tool_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    tool_use_id = str(tool_call.get("id") or "")
    output = _output_for_tool_call(tool_call, tool_results)
    status = "error" if isinstance(output, str) and output.strip().lower().startswith("error") else "done"
    return {
        "id": tool_use_id,
        "name": str(tool_call.get("name") or ""),
        "input": tool_call.get("input") if isinstance(tool_call.get("input"), dict) else {},
        "output": output,
        "status": status,
    }


def _output_for_tool_call(
    tool_call: dict[str, Any],
    tool_results: dict[str, dict[str, Any]],
) -> str | None:
    result = tool_results.get(str(tool_call.get("id") or ""))
    if not result:
        return None
    content = result.get("content")
    return _content_text(content)


def _tool_summary(tool_payload: dict[str, Any]) -> str:
    target = _tool_target(tool_payload["name"], tool_payload["input"])
    if target:
        return f"{tool_payload['name']} -> {target}"
    return tool_payload["name"]


def _tool_target(name: str, tool_input: dict[str, Any]) -> str:
    for key in ("path", "command", "url", "pattern"):
        value = tool_input.get(key)
        if value:
            return str(value)
    return name


def _change_type(name: str, output: str) -> str:
    if name == "edit_file" and output.strip().lower().startswith("created"):
        return "created"
    if name == "write_file":
        return "modified"
    return "modified"


def _node_label(record: dict[str, Any]) -> str:
    record_type = record.get("type")
    if record_type == "message":
        return str((record.get("message") or {}).get("role") or "message")
    if record_type == "tool_call":
        return str((record.get("toolCall") or {}).get("name") or "tool")
    if record_type == "tool_result":
        return "tool result"
    if record_type == "compaction":
        return "compaction"
    if record_type == "branch_summary":
        return "branch"
    return str(record_type or "")


def _record_preview(record: dict[str, Any]) -> str:
    record_type = record.get("type")
    if record_type == "message":
        return _preview_text((record.get("message") or {}).get("content"), 160)
    if record_type == "tool_call":
        tool_call = record.get("toolCall") or {}
        return _tool_summary(
            {
                "name": str(tool_call.get("name") or ""),
                "input": tool_call.get("input") if isinstance(tool_call.get("input"), dict) else {},
            }
        )
    if record_type == "tool_result":
        return _preview_text((record.get("toolResult") or {}).get("content"), 160)
    if record_type in {"branch_summary", "compaction"}:
        return _preview_text(record.get("summary"), 160)
    if record_type == "label":
        return str(record.get("label") or "")
    return _preview_text(record, 160)


def _preview_text(content: Any, max_chars: int) -> str:
    text = _content_text(content)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type in {"text", "reasoning"}:
                    parts.append(str(item.get("text") or ""))
                elif item_type == "tool_use":
                    parts.append(f"tool:{item.get('name') or ''}")
                elif item_type == "tool_result":
                    parts.append(str(item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part).strip()
    try:
        return json.dumps(content, ensure_ascii=False, indent=2)
    except TypeError:
        return str(content)
