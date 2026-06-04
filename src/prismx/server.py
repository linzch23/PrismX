from __future__ import annotations

import json
import mimetypes
import os
import threading
from dataclasses import asdict, is_dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .loop import AgentApp
from .tree_session import (
    BranchSummaryEntry,
    CompactionEntry,
    MessageEntry,
    ToolCallEntry,
    ToolResultEntry,
)
from .web_adapter import (
    load_session_records,
    memory_payload,
    records_to_file_changes,
    records_to_node_detail,
    records_to_run_steps,
    records_to_tool_events,
    records_to_tree_nodes,
)
from .workspace import WorkspaceStore


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class WebState:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.frontend_dir = root / "frontend"
        self.app = AgentApp(root=root)
        self.workspace = WorkspaceStore(root, self.app.tree)
        payload = self.workspace.payload()
        if payload.get("activeTreeId"):
            self.app.active_tree_id = str(payload["activeTreeId"])
        self.lock = threading.RLock()

    def close(self) -> None:
        self.app.close()

    def select_session(self, session_id: str) -> None:
        self.workspace.select_backend_session(session_id)
        payload = self.workspace.payload()
        if payload.get("activeTreeId"):
            self.app.active_tree_id = str(payload["activeTreeId"])
        self.app.session_id = session_id
        self.app.history = self.app.tree.buildModelContext(session_id)


def main() -> None:
    root = Path(os.getenv("MY_AGENT_ROOT", Path.cwd())).resolve()
    host = os.getenv("MY_AGENT_WEB_HOST", DEFAULT_HOST)
    port = int(os.getenv("MY_AGENT_WEB_PORT", str(DEFAULT_PORT)))
    state = WebState(root)
    server = ThreadingHTTPServer((host, port), _handler_factory(state))
    print(f"prismx web 已就绪：http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
        state.close()


def _handler_factory(state: WebState):
    class Handler(BaseHTTPRequestHandler):
        server_version = "prismx-web/0.1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)
            try:
                if path == "/api/health":
                    self._send_json({"ok": True})
                    return
                if path == "/api/state":
                    filter_mode = query.get("filter", ["default"])[0]
                    with state.lock:
                        self._send_json(_state_payload(state.app, filter_mode=filter_mode))
                    return
                if path == "/api/sessions":
                    with state.lock:
                        self._send_json(_sessions_payload(state.app))
                    return
                if path == "/api/workspace":
                    with state.lock:
                        self._send_json(_workspace_payload(state))
                    return
                session_route = _session_resource_route(path)
                if session_route is not None:
                    session_id, resource, node_id = session_route
                    with state.lock:
                        self._send_json(_session_resource_payload(state, session_id, resource, node_id))
                    return
                if path == "/api/tree":
                    filter_mode = query.get("filter", ["default"])[0]
                    with state.lock:
                        self._send_json(_tree_payload(state.app, filter_mode=filter_mode))
                    return
                if path == "/api/context/debug":
                    with state.lock:
                        self._send_json(state.app.tree.debugBuildModelContext(state.app.session_id))
                    return
                if path == "/api/context":
                    prefix = query.get("prefix", [""])[0]
                    limit = int(query.get("limit", ["200"])[0])
                    with state.lock:
                        self._send_json({"objects": state.app.memory.list_context(prefix=prefix, limit=limit)})
                    return
                if path == "/api/tools":
                    with state.lock:
                        self._send_json({"tools": state.app.registry.definitions()})
                    return
                if path == "/api/memory":
                    with state.lock:
                        self._send_json(memory_payload(state.app.memory.memory_dir))
                    return
                if path == "/api/mcp":
                    with state.lock:
                        self._send_json({"report": state.app.mcp.report()})
                    return
                if path == "/api/team":
                    with state.lock:
                        self._send_json({"team": state.app.team.list_all()})
                    return
                self._serve_static(path, state.frontend_dir)
            except Exception as exc:
                self._send_error(exc)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/api/chat/stream":
                    self._chat_stream()
                    return
                payload = self._read_json()
                with state.lock:
                    if path == "/api/chat":
                        message = str(payload.get("message", "")).strip()
                        if not message:
                            raise ValueError("message is required")
                        reply = state.app.ask(message)
                        self._send_json({"reply": reply, "state": _state_payload(state.app)})
                        return
                    if path == "/api/projects":
                        name = str(payload.get("name") or payload.get("title") or "").strip() or "New Project"
                        state.workspace.create_project(
                            name,
                            name=name,
                            workspace_name=str(payload.get("workspaceName") or "").strip(),
                            workspace_display_path=str(payload.get("workspaceDisplayPath") or "").strip(),
                        )
                        self._send_json(_workspace_payload(state), status=HTTPStatus.CREATED)
                        return
                    if path == "/api/session-trees":
                        project_id = str(payload.get("projectId", "")).strip()
                        title = str(payload.get("title", "")).strip() or "New Session Tree"
                        workspace = state.workspace.create_session_tree(project_id, title)
                        state.select_session(str(workspace["activeSessionId"]))
                        self._send_json(_workspace_payload(state), status=HTTPStatus.CREATED)
                        return
                    if path == "/api/session-nodes":
                        tree_id = str(payload.get("treeId", "")).strip()
                        parent_id = str(payload.get("parentId", "")).strip()
                        title = str(payload.get("title", "")).strip() or "New Session"
                        workspace = state.workspace.create_session_node(tree_id, parent_id, title)
                        state.select_session(str(workspace["activeSessionId"]))
                        self._send_json(_workspace_payload(state), status=HTTPStatus.CREATED)
                        return
                    node_route = _session_node_route(path)
                    if node_route and node_route[1] == "select":
                        workspace = state.workspace.select_session_node(node_route[0])
                        if workspace.get("activeSessionId"):
                            state.select_session(str(workspace["activeSessionId"]))
                        self._send_json(_workspace_payload(state))
                        return
                    if path == "/api/tree/jump":
                        state.app.jump_to_entry(_entry_id(payload))
                        self._send_json(_state_payload(state.app))
                        return
                    if path == "/api/tree/fork":
                        state.app.fork_from_entry(_entry_id(payload))
                        self._send_json(_state_payload(state.app))
                        return
                    if path == "/api/tree/clone":
                        state.app.clone_active_branch()
                        self._send_json(_state_payload(state.app))
                        return
                    if path == "/api/tree/label":
                        state.app.label_entry(_entry_id(payload), str(payload.get("label", "")).strip())
                        self._send_json(_state_payload(state.app))
                        return
                    if path == "/api/compact":
                        compacted = state.app.compact_now()
                        self._send_json({"compacted": compacted, "state": _state_payload(state.app)})
                        return
                    if path == "/api/sessions/select":
                        session_id = str(payload.get("sessionId", "")).strip()
                        if session_id not in state.app.tree.listSessions():
                            raise KeyError(f"session not found: {session_id}")
                        state.select_session(session_id)
                        self._send_json(_state_payload(state.app))
                        return
                    if path == "/api/sessions":
                        title = str(payload.get("title", "")).strip() or None
                        session_id = state.app.tree.createSession(title=title, cwd=str(state.app.workspace))
                        state.select_session(session_id)
                        self._send_json(_state_payload(state.app), status=HTTPStatus.CREATED)
                        return
                self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_error(exc)

        def do_PATCH(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                payload = self._read_json()
                project_route = _project_route(path)
                if project_route:
                    with state.lock:
                        state.workspace.update_project(project_route, payload)
                        self._send_json(_workspace_payload(state))
                        return
                tree_route = _session_tree_route(path)
                if tree_route:
                    with state.lock:
                        state.workspace.update_session_tree(tree_route, payload)
                        self._send_json(_workspace_payload(state))
                        return
                node_route = _session_node_route(path)
                if node_route and node_route[1] is None:
                    with state.lock:
                        state.workspace.update_session_node(node_route[0], payload)
                        self._send_json(_workspace_payload(state))
                        return
                self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_error(exc)

        def do_DELETE(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                project_route = _project_route(path)
                if project_route:
                    with state.lock:
                        workspace = state.workspace.delete_project(project_route)
                        if workspace.get("activeSessionId"):
                            state.select_session(str(workspace["activeSessionId"]))
                        self._send_json(_workspace_payload(state))
                        return
                tree_route = _session_tree_route(path)
                if tree_route:
                    with state.lock:
                        workspace = state.workspace.delete_session_tree(tree_route)
                        if workspace.get("activeSessionId"):
                            state.select_session(str(workspace["activeSessionId"]))
                        self._send_json(_workspace_payload(state))
                        return
                node_route = _session_node_route(path)
                if node_route and node_route[1] is None:
                    with state.lock:
                        workspace = state.workspace.delete_session_node(node_route[0])
                        if workspace.get("activeSessionId"):
                            state.select_session(str(workspace["activeSessionId"]))
                        self._send_json(_workspace_payload(state))
                        return
                self.send_error(HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_error(exc)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _chat_stream(self) -> None:
            payload = self._read_json()
            message = str(payload.get("message", "")).strip()
            if not message:
                self._send_json({"error": "message is required"}, status=HTTPStatus.BAD_REQUEST)
                return
            session_id = str(payload.get("sessionId", "")).strip()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            def emit(event: str, data: dict[str, Any]) -> None:
                self._write_sse(event, data)

            try:
                with state.lock:
                    if session_id:
                        state.select_session(session_id)
                    emit("user_message", {"text": message})
                    reply = state.app.ask(
                        message,
                        on_text_delta=lambda text: emit("delta", {"text": text}),
                        on_tool_call=lambda block: emit("tool_call", _plain_data(block)),
                        on_tool_result=lambda result: emit("tool_result", result),
                        workspace_context=_workspace_context_for_session(state, session_id) if session_id else None,
                    )
                    emit("done", {"reply": reply, "state": _state_payload(state.app)})
            except BrokenPipeError:
                return
            except Exception as exc:
                emit("error", {"error": str(exc)})

        def _serve_static(self, path: str, frontend_dir: Path) -> None:
            if path in {"", "/"}:
                target = frontend_dir / "index.html"
            else:
                target = (frontend_dir / path.lstrip("/")).resolve()
                try:
                    target.relative_to(frontend_dir.resolve())
                except ValueError as exc:
                    raise FileNotFoundError(path) from exc
            if not target.exists() or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            body = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            if not raw.strip():
                return {}
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("JSON body must be an object")
            return data

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, exc: Exception) -> None:
            status = HTTPStatus.BAD_REQUEST if isinstance(exc, (KeyError, ValueError)) else HTTPStatus.INTERNAL_SERVER_ERROR
            self._send_json({"error": str(exc)}, status=status)

        def _write_sse(self, event: str, payload: dict[str, Any]) -> None:
            data = json.dumps(payload, ensure_ascii=False)
            self.wfile.write(f"event: {event}\n".encode("utf-8"))
            for line in data.splitlines() or [""]:
                self.wfile.write(f"data: {line}\n".encode("utf-8"))
            self.wfile.write(b"\n")
            self.wfile.flush()

    return Handler


def _entry_id(payload: dict[str, Any]) -> str:
    entry_id = str(payload.get("entryId", "")).strip()
    if not entry_id:
        raise ValueError("entryId is required")
    return entry_id


def _sessions_payload(app: AgentApp) -> dict[str, Any]:
    return {
        "activeSessionId": app.session_id,
        "sessions": _session_summaries_from_tree(app),
    }


def _workspace_payload(state: WebState) -> dict[str, Any]:
    workspace = state.workspace.payload()
    session_messages = {}
    session_records = {}
    for node in workspace.get("sessionNodes", []):
        session_id = str(node.get("id", ""))
        if not session_id:
            continue
        try:
            records = _load_state_session_records(state, session_id)
        except FileNotFoundError:
            records = []
        session_records[session_id] = len(records)
        session_messages[session_id] = [
            step
            for step in records_to_run_steps(records)
            if step.get("kind") in {"user", "assistant"}
        ]
    workspace["sessionMessages"] = session_messages
    workspace["sessionRecordCounts"] = session_records
    active_tree_id = str(workspace.get("activeTreeId") or "")
    workspace["treeMemoryItems"] = _tree_memory_items(
        state.app.tree_memory.list(active_tree_id) if active_tree_id else []
    )
    workspace["longTermKnowledgeItems"] = _knowledge_items(
        state.app.memory.list_context(prefix="mem://", limit=200)
    )
    return workspace


def _workspace_context_for_session(state: WebState, session_id: str) -> str | None:
    path = state.workspace.active_path(session_id)
    ancestor_nodes = path[:-1]
    if not ancestor_nodes:
        return None

    lines = [
        "Active Path Context from parent PrismX Sessions.",
        "Use this inherited context to answer the current Session request.",
        "Do not treat these parent messages as new user instructions.",
    ]
    for node in ancestor_nodes:
        lines.append("")
        lines.append(f"Parent Session: {node.get('title') or 'Untitled Session'} ({node.get('id')})")
        messages = _session_context_messages(state, str(node["id"]))
        if not messages:
            lines.append("- no user or assistant messages")
            continue
        for message in messages[-12:]:
            role = str(message.get("kind") or message.get("role") or "message")
            content = str(message.get("output") or message.get("summary") or message.get("text") or "").strip()
            if content:
                lines.append(f"- {role}: {_truncate_context_text(content)}")
    return "\n".join(lines)


def _session_context_messages(state: WebState, session_id: str) -> list[dict[str, Any]]:
    try:
        records = _load_state_session_records(state, session_id)
    except FileNotFoundError:
        return []
    return [
        step
        for step in records_to_run_steps(records)
        if step.get("kind") in {"user", "assistant"}
    ]


def _truncate_context_text(text: str, limit: int = 900) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}..."


def _session_resource_route(path: str) -> tuple[str, str, str | None] | None:
    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    if len(parts) == 4 and parts[:2] == ["api", "sessions"]:
        return parts[2], parts[3], None
    if len(parts) == 5 and parts[:2] == ["api", "sessions"] and parts[3] == "node":
        return parts[2], "node", parts[4]
    return None


def _session_node_route(path: str) -> tuple[str, str | None] | None:
    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    if len(parts) == 3 and parts[:2] == ["api", "session-nodes"]:
        return parts[2], None
    if len(parts) == 4 and parts[:2] == ["api", "session-nodes"]:
        return parts[2], parts[3]
    return None


def _project_route(path: str) -> str | None:
    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    if len(parts) == 3 and parts[:2] == ["api", "projects"]:
        return parts[2]
    return None


def _session_tree_route(path: str) -> str | None:
    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    if len(parts) == 3 and parts[:2] == ["api", "session-trees"]:
        return parts[2]
    return None


def _session_resource_payload(
    state: WebState,
    session_id: str,
    resource: str,
    node_id: str | None,
) -> Any:
    records = _load_state_session_records(state, session_id)
    if resource == "raw":
        return {"sessionId": session_id, "records": records}
    if resource == "runs":
        return {
            "sessionId": session_id,
            "runs": records_to_run_steps(records),
            "fileChanges": records_to_file_changes(records),
            "toolEvents": records_to_tool_events(records),
        }
    if resource == "tree":
        return {"sessionId": session_id, "nodes": records_to_tree_nodes(records)}
    if resource == "node" and node_id:
        return {"sessionId": session_id, **records_to_node_detail(records, node_id)}
    raise KeyError(f"unknown session resource: {resource}")


def _state_payload(app: AgentApp, *, filter_mode: str = "default") -> dict[str, Any]:
    return {
        "provider": app.provider,
        "model": app.model,
        "workspace": str(app.workspace),
        "sessionId": app.session_id,
        "sessions": app.tree.listSessions(),
        "tree": _tree_payload(app, filter_mode=filter_mode),
        "tools": app.registry.names(),
        "todos": app.todos.render(),
        "mcp": app.mcp.report(),
        "team": app.team.list_all(),
    }


def _tree_payload(app: AgentApp, *, filter_mode: str = "default") -> dict[str, Any]:
    session = app.tree.sessions[app.session_id]
    debug = app.tree.debugBuildModelContext(app.session_id)
    nodes = []
    for entry in session.entries:
        if not app.tree._is_tree_entry(entry):  # TreeSessionManager owns the JSONL replay rules.
            continue
        nodes.append(
            {
                "id": entry.id,
                "type": entry.type,
                "parentId": entry.parentId,
                "timestamp": entry.timestamp,
                "metadata": entry.metadata,
                "label": session.labels.get(entry.id),
                "active": entry.id == session.activeLeafId,
                "visible": _visible(entry, filter_mode, session.labels),
                "preview": _entry_preview(entry),
                "contextLayer": app.tree.getContextLayer(app.session_id, entry.id).name,
                "data": _plain_data(entry),
            }
        )
    return {
        "sessionId": app.session_id,
        "filePath": str(app.tree.getSessionFilePath(app.session_id)),
        "activeLeafId": session.activeLeafId,
        "rootId": session.rootId,
        "title": session.title,
        "nodes": nodes,
        "childrenByParent": session.childrenByParent,
        "labels": session.labels,
        "debug": debug,
        "rendered": app.tree.render_tree(app.session_id, filter_mode=filter_mode),
    }


def _visible(entry: Any, filter_mode: str, labels: dict[str, str | None]) -> bool:
    if filter_mode == "all":
        return True
    if filter_mode == "labeled-only":
        return bool(labels.get(entry.id))
    if filter_mode == "user-only":
        return isinstance(entry, MessageEntry) and entry.message.get("role") == "user"
    if filter_mode == "no-tools":
        return not isinstance(entry, (ToolCallEntry, ToolResultEntry))
    return not isinstance(entry, ToolCallEntry)


def _entry_preview(entry: Any) -> str:
    if isinstance(entry, MessageEntry):
        return _content_preview(entry.message.get("content", ""))
    if isinstance(entry, ToolCallEntry):
        return str(entry.toolCall.get("name", ""))[:120]
    if isinstance(entry, ToolResultEntry):
        return _content_preview(entry.toolResult.get("content", ""))
    if isinstance(entry, BranchSummaryEntry):
        return entry.summary[:120]
    if isinstance(entry, CompactionEntry):
        return entry.summary[:120]
    return ""


def _content_preview(content: Any) -> str:
    if isinstance(content, str):
        return content.replace("\n", " ")[:160]
    if isinstance(content, list):
        parts = []
        for item in content:
            data = _plain_data(item)
            if isinstance(data, dict):
                if data.get("type") == "text":
                    parts.append(str(data.get("text", "")))
                elif data.get("type") == "tool_use":
                    parts.append(f"tool:{data.get('name', '')}")
                elif data.get("type") == "tool_result":
                    parts.append(str(data.get("content", "")))
            else:
                parts.append(str(data))
        return " ".join(part for part in parts if part).replace("\n", " ")[:160]
    return str(content).replace("\n", " ")[:160]


def _plain_data(value: Any) -> Any:
    if is_dataclass(value):
        return _plain_data(asdict(value))
    if isinstance(value, list):
        return [_plain_data(item) for item in value]
    if isinstance(value, tuple):
        return [_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain_data(item) for key, item in value.items()}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return _plain_data({key: item for key, item in vars(value).items() if not key.startswith("_")})
    return str(value)


def _load_state_session_records(state: WebState, session_id: str) -> list[dict[str, Any]]:
    tree = state.app.tree if hasattr(state, "app") else getattr(state, "tree", state.workspace.tree)
    path = tree.getSessionFilePath(session_id)
    if not path.exists():
        raise FileNotFoundError(f"session not found: {session_id}")
    return load_session_records(session_id, path.parent)


def _session_summaries_from_tree(app: AgentApp) -> list[dict[str, Any]]:
    summaries = []
    for session_id in app.tree.listSessions():
        try:
            path = app.tree.getSessionFilePath(session_id)
            records = load_session_records(session_id, path.parent)
        except FileNotFoundError:
            continue
        info = next((record for record in records if record.get("type") == "session_info"), {})
        summaries.append(
            {
                "id": session_id,
                "filePath": str(path),
                "title": info.get("title"),
                "recordCount": len(records),
                "createdAt": info.get("createdAt") or (records[0].get("timestamp") if records else None),
                "updatedAt": next((str(record["timestamp"]) for record in reversed(records) if record.get("timestamp")), None),
            }
        )
    return sorted(summaries, key=lambda item: (str(item.get("updatedAt") or ""), str(item.get("id") or "")))


def _tree_memory_items(objects: list[Any]) -> list[dict[str, Any]]:
    items = []
    for item in objects:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "")
        context_type = str(item.get("context_type") or item.get("type") or "")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        if uri.startswith("tree://") or "tree" in context_type:
            items.append(
                {
                    "id": uri or str(item.get("id") or ""),
                    "treeId": str(item.get("tree_id") or item.get("treeId") or metadata.get("tree_id") or ""),
                    "sourceSessionId": str(
                        item.get("source_session_id")
                        or item.get("sourceSessionId")
                        or metadata.get("source_session_id")
                        or metadata.get("source_branch")
                        or ""
                    ),
                    "type": str(item.get("memory_type") or metadata.get("memory_type") or item.get("type") or context_type or "finding"),
                    "content": str(item.get("overview") or item.get("content") or item.get("title") or uri),
                    "reuseCount": int(metadata.get("reuse_count") or item.get("reuse_count") or 0),
                    "confidence": float(metadata.get("confidence") or item.get("trust_score") or item.get("confidence") or 0.0),
                    "status": str(metadata.get("status") or item.get("status") or "active"),
                    "promoted": bool(metadata.get("promoted") or item.get("promoted") or False),
                    "createdAt": str(item.get("created_at") or item.get("createdAt") or ""),
                }
            )
    return items


def _knowledge_items(objects: list[Any]) -> list[dict[str, Any]]:
    items = []
    for item in objects:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "")
        context_type = str(item.get("context_type") or item.get("type") or "")
        if uri.startswith("mem://") or uri.startswith("wiki://") or "knowledge" in context_type:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            items.append(
                {
                    "id": uri or str(item.get("id") or ""),
                    "title": str(item.get("title") or uri or "Knowledge"),
                    "content": str(item.get("overview") or item.get("content") or ""),
                    "type": str(metadata.get("type") or metadata.get("knowledge_type") or item.get("type") or ""),
                    "sourceTreeId": str(metadata.get("source_tree_id") or ""),
                    "sourceMemoryId": str(metadata.get("source_memory_id") or ""),
                    "confidence": float(metadata.get("confidence") or item.get("trust_score") or 0.0),
                    "status": str(metadata.get("status") or item.get("status") or "active"),
                    "createdAt": str(item.get("created_at") or item.get("createdAt") or ""),
                }
            )
    return items


if __name__ == "__main__":
    main()
